"""Test harness: a running server and sessions that talk to it the way a coding agent does."""

from __future__ import annotations

import hashlib
import io
import os
import threading
import time
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import Future
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode

import httpx
import httpx2
import psycopg
import pytest
import uvicorn
from anyio.from_thread import BlockingPortal
from mcp import Client, types
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from shared_memory import cli
from shared_memory.config import Settings

ADMIN_URL = os.environ.get("SHARED_MEMORY_TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5433/postgres")
REPO_ROOT = Path(__file__).resolve().parent.parent

# What Claude Code calls each event it hooks, which is what its payloads name.
CLAUDE_EVENTS = {"session-start": "SessionStart", "prompt-submitted": "UserPromptSubmit"}


# Each checkout names its own test databases, so two worktrees can run their tests against one Postgres at once.
CHECKOUT = hashlib.sha1(str(REPO_ROOT).encode()).hexdigest()[:8]


def fresh_database(name: str) -> str:
    """Drop and recreate this checkout's database of that name on the test Postgres; return its URL."""
    name = f"{name}_{CHECKOUT}"
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {name}")
    except psycopg.OperationalError as error:
        pytest.exit(f"Postgres is not reachable ({error}). Start it with: docker compose up -d db", returncode=2)
    return ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"


class TestClock:
    """A clock the tests move by hand."""

    __test__ = False

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class ToolRefused(Exception):
    """A tool call came back as an error result."""


class RunningServer:
    def __init__(
        self, app: Any, settings: Settings, clock: TestClock, portal: BlockingPortal, port: int = 0
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.portal = portal
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 30
        while not self._server.started:
            if time.monotonic() > deadline or not self._thread.is_alive():
                raise RuntimeError("test server did not start")
            time.sleep(0.05)
        port = self._server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)

    def join(self) -> None:
        """Stay up until the process is stopped, for a server the browser journeys run against."""
        self._thread.join()

    def run_cli(self, *argv: str) -> str:
        out = io.StringIO()
        code = cli.run(list(argv), settings=self.settings, out=out)
        if code != 0:
            raise RuntimeError(f"command {argv} failed: {out.getvalue()}")
        return out.getvalue()


@dataclass
class Session:
    """One session of a member's coding agent, as the server sees it."""

    server: RunningServer
    token: str | None
    project: str | None = None
    repository: str | None = None
    # The name the session's coding agent reports for itself when it connects, e.g. "codex-mcp-client".
    agent: str | None = None

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.project is not None:
            headers["X-Shared-Memory-Project"] = self.project
        if self.repository is not None:
            headers["X-Shared-Memory-Repository"] = self.repository
        return headers

    def in_project(self, project: str, repository: str = "app") -> Session:
        return Session(self.server, self.token, project, repository, self.agent)

    def as_agent(self, name: str) -> Session:
        """The same member and project, from a coding agent that reports itself by this name."""
        return Session(self.server, self.token, self.project, self.repository, name)

    def _client(self, transport: Any) -> Client:
        info = types.Implementation(name=self.agent, version="1.0") if self.agent else None
        return Client(transport, client_info=info)

    def call(self, tool: str, **arguments: Any) -> Any:
        """Call an MCP tool; return its structured result or raise ToolRefused with its message."""
        return self.server.portal.call(self._call, tool, arguments)

    def call_soon(self, tool: str, **arguments: Any) -> Future[Any]:
        """Start an MCP tool call without waiting for it; the future holds what `call` would return."""
        return self.server.portal.start_task_soon(self._call, tool, arguments)

    async def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        async with self._connected() as client:
            result = await client.call_tool(tool, arguments)
        text = "\n".join(getattr(part, "text", "") for part in result.content)
        if result.is_error:
            raise ToolRefused(text)
        if result.structured_content is not None:
            structured = result.structured_content
            if set(structured) == {"result"}:
                return structured["result"]
            return structured
        return text

    def run_prompt(self, name: str) -> str:
        """Fetch an MCP prompt the way an agent offers it as a command; return its text."""
        return self.server.portal.call(self._run_prompt, name)

    async def _run_prompt(self, name: str) -> str:
        async with self._connected() as client:
            result = await client.get_prompt(name)
        return "\n".join(getattr(message.content, "text", "") for message in result.messages)

    def on_connecting(self) -> tuple[str, dict[str, str]]:
        """What an agent is given when it connects: the server's instructions, and each tool's description."""
        return self.server.portal.call(self._on_connecting)

    async def _on_connecting(self) -> tuple[str, dict[str, str]]:
        async with self._connected() as client:
            tools = await client.list_tools()
            instructions = client.instructions or ""
        return instructions, {tool.name: tool.description or "" for tool in tools.tools}

    @asynccontextmanager
    async def _connected(self) -> AsyncIterator[Client]:
        """A connection to the server's MCP endpoint, made the way this member's agent makes it."""
        async with AsyncExitStack() as stack:
            http = await stack.enter_async_context(httpx2.AsyncClient(headers=self.headers(), timeout=60))
            transport = streamable_http_client(f"{self.server.url}/mcp", http_client=http)
            yield await stack.enter_async_context(self._client(transport))

    def refusal(self, tool: str, **arguments: Any) -> str:
        """Call a tool that is expected to be refused; return the refusal message."""
        try:
            self.call(tool, **arguments)
        except ToolRefused as refused:
            return str(refused)
        raise AssertionError(f"{tool} was not refused")

    def _hook(self, event: str, payload: dict[str, Any], format: str | None = None) -> dict[str, Any]:
        body = {"session_id": "test-session", "cwd": "/work/app", "hook_event_name": CLAUDE_EVENTS[event], **payload}
        return self.hook_payload(event, body, format)

    def hook_payload(self, event: str, payload: dict[str, Any], format: str | None = None) -> dict[str, Any]:
        """Post one hook payload exactly as an agent's hook sends it, asking for an agent family's answer format."""
        response = httpx.post(
            f"{self.server.url}/hooks/{event}",
            json=payload,
            params={"format": format} if format else None,
            headers=self.headers(),
            timeout=60,
        )
        assert response.status_code == 200, response.text
        data: dict[str, Any] = response.json()
        return data

    def start(self, format: str | None = None) -> dict[str, Any]:
        """Fire the session-start hook and return its hook output."""
        return self._hook("session-start", {"source": "startup"}, format)

    def prompt(self, text: str, format: str | None = None) -> dict[str, Any]:
        """Fire the prompt-submitted hook and return its hook output."""
        return self._hook("prompt-submitted", {"prompt": text}, format)


def added_context(hook_output: dict[str, Any]) -> str:
    specific = hook_output.get("hookSpecificOutput") or {}
    context: str = specific.get("additionalContext", "")
    return context


@dataclass
class Team:
    server: RunningServer
    code: str
    owner_token: str

    def owner(self) -> Session:
        return Session(self.server, self.owner_token)


def new_team(server: RunningServer) -> Team:
    code = f"team-{uuid.uuid4().hex[:8]}"
    output = server.run_cli("setup", "--team", code, "--owner-member-id", "owner-1", "--owner-name", "Olive Owner")
    token = next(line.split(":", 1)[1].strip() for line in output.splitlines() if line.startswith("Owner personal token:"))
    return Team(server, code, token)


def member(team: Team, project: str, member_id: str, name: str) -> Session:
    """A session for a member added to the team, working in one project."""
    added = team.owner().call("add_member", member_id=member_id, name=name)
    return Session(team.server, added["personal_token"], project, "billing-api")


# Two memories that contradict each other, so promoting the second finds the first similar.
NPM = {
    "title": "Use npm for installs",
    "summary": "Packages are installed with npm.",
    "type": "convention",
    "body": "Install dependencies with npm install. Do not use other package managers.",
}
PNPM = {
    "title": "Use pnpm, not npm",
    "summary": "Every package uses pnpm.",
    "type": "convention",
    "body": "We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
}


def promote_now(session: Session, memory: dict[str, str], level: str = "project") -> str:
    """Promote a memory that has nothing similar to resolve."""
    result = session.call("promote", path=session.call("remember", **memory)["path"], level=level)
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def promote_keeping_both(session: Session, memory: dict[str, str], level: str = "project") -> str:
    """Promote a memory that reads as similar to others but contradicts none of them.

    Similarity is generous — two memories about entirely different things can sit above the threshold — so a
    seed that adds a memory to a team which already has a few cannot assume nothing will come back.
    """
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level=level)
    if first["status"] == "promoted":
        return str(first["path"])
    assert first["status"] == "similar_memories", first
    result = session.call(
        "promote",
        path=personal,
        level=level,
        reference=first["reference"],
        resolutions={similar["path"]: "keep_both" for similar in first["similar"]},
    )
    assert result["status"] == "promoted", result
    return str(result["path"])


def _supersede(session: Session, personal: str, target: str, level: str, reasoning: str | None = None) -> dict[str, Any]:
    first = session.call("promote", path=personal, level=level)
    assert first["status"] == "similar_memories", first
    resolutions = {similar["path"]: ("supersede" if similar["path"] == target else "keep_both") for similar in first["similar"]}
    result: dict[str, Any] = session.call(
        "promote", path=personal, level=level, reference=first["reference"], resolutions=resolutions, reasoning=reasoning
    )
    return result


def promote_superseding(session: Session, memory: dict[str, str], target: str, level: str = "project") -> dict[str, Any]:
    """Promote a memory over one it supersedes, keeping anything else similar."""
    return _supersede(session, session.call("remember", **memory)["path"], target, level)


def challenge(
    session: Session, memory: dict[str, str], target: str, level: str = "project", reasoning: str | None = None
) -> dict[str, Any]:
    """Raise a challenge: supersede another author's memory, which they decide."""
    personal = session.call("remember", **memory)["path"]
    result = _supersede(session, personal, target, level, reasoning)
    assert result["status"] == "challenge_raised", result
    return {**result, "personal": personal}


class FakeGitHub:
    """Stands in for GitHub's sign-in, so no test touches the real one.

    It signs everyone in as whichever account it has been told to return, which is how a test chooses who is at the
    keyboard. The browser journeys change that account through `POST /as-account`.
    """

    def __init__(self, portal: BlockingPortal, settings: Settings, port: int = 0) -> None:
        self.account_id = 1
        self.login = "olive"
        # The login each account number was first used with. It lives as long as this fake GitHub does, which is as
        # long as the server whose database remembers the same thing.
        self._logins: dict[int, str] = {}

        async def authorize(request: Request) -> Response:
            redirect_uri = request.query_params["redirect_uri"]
            state = request.query_params.get("state", "")
            joiner = "&" if "?" in redirect_uri else "?"
            return RedirectResponse(f"{redirect_uri}{joiner}code=fake-code&state={state}", status_code=302)

        async def access_token(request: Request) -> Response:
            return JSONResponse({"access_token": "gho_fake", "token_type": "bearer", "scope": "read:user"})

        async def user(request: Request) -> Response:
            return JSONResponse({"id": self.account_id, "login": self.login})

        async def as_account(request: Request) -> Response:
            body = await request.json()
            try:
                self.as_(int(body["id"]), str(body["login"]))
            except AssertionError as refused:
                return JSONResponse({"error": str(refused)}, status_code=409)
            return JSONResponse({"id": self.account_id, "login": self.login})

        app = Starlette(
            routes=[
                Route("/login/oauth/authorize", authorize, methods=["GET"]),
                Route("/login/oauth/access_token", access_token, methods=["POST"]),
                Route("/user", user, methods=["GET"]),
                Route("/as-account", as_account, methods=["POST"]),
            ]
        )
        self._server = RunningServer(app, settings, TestClock(), portal, port=port)
        self.url = self._server.url

    def as_(self, account_id: int, login: str, renamed: bool = False) -> None:
        """Whoever signs in next is this GitHub account.

        An account number belongs to the first login that used it here. The server links a number to one member, so
        a second login under that number would be refused at sign-in with nothing to say why; this fails first, and
        names both. `renamed` is for the test that means it: the same account, under a new login.
        """
        taken_by = self._logins.setdefault(account_id, login)
        assert taken_by == login or renamed, (
            f"GitHub account number {account_id} is already {taken_by!r} in this fake GitHub, so {login!r} cannot "
            "sign in with it. Give one of the two tests a number no other test in the module uses."
        )
        self._logins[account_id] = login
        self.account_id, self.login = account_id, login

    def stop(self) -> None:
        self._server.stop()


class ConsoleClient:
    """A browser, as the server sees it: it follows redirects and keeps the session cookie."""

    def __init__(self, server: RunningServer) -> None:
        self.server = server
        self._http = httpx.Client(base_url=server.url, follow_redirects=True, timeout=30)

    def status(self) -> dict[str, Any]:
        response = self._http.get("/api/status")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def get(self, path: str) -> httpx.Response:
        return self._http.get(path)

    def sign_in(self) -> httpx.Response:
        """Follow the whole sign-in: to GitHub, back to the callback, and on to the console."""
        return self._http.get("/api/sign-in/github")

    def post(self, path: str, with_header: bool = True) -> httpx.Response:
        headers = {"X-Shared-Memory-Console": "1"} if with_header else {}
        return self._http.post(path, headers=headers)

    def post_json(self, path: str, body: dict[str, Any]) -> httpx.Response:
        return self._http.post(path, json=body, headers={"X-Shared-Memory-Console": "1"})

    def sign_out(self, with_header: bool = True) -> httpx.Response:
        return self.post("/api/sign-out", with_header)

    def close(self) -> None:
        self._http.close()


def sign_in_error(response: httpx.Response) -> str:
    """The message the console was sent back with, when a sign-in was refused."""
    return unquote(str(response.url.params.get("sign-in-error", "")))


@dataclass
class Console:
    """A server with GitHub sign-in set up, and the fake GitHub it signs people in through."""

    server: RunningServer
    github: FakeGitHub
    clock: TestClock

    def client(self) -> ConsoleClient:
        return ConsoleClient(self.server)

    def a_team(self, github_login: str) -> tuple[str, str]:
        """A team whose owner signs in as this GitHub account; returns the team's code and the owner's token."""
        code = f"team-{uuid.uuid4().hex[:8]}"
        printed = self.server.run_cli(
            "setup", "--team", code, "--owner-member-id", "E1001", "--owner-name", "Olive Owner",
            "--owner-github", github_login,
        )  # fmt: skip
        token = next(line.split(":", 1)[1].strip() for line in printed.splitlines() if line.startswith("Owner personal"))
        return code, token


def signed_in(console: Console, github: str, account: int) -> ConsoleClient:
    """A console client signed in as one GitHub account."""
    client = console.client()
    console.github.as_(account, github)
    client.sign_in()
    return client


def signed_in_owner(console: Console, client: ConsoleClient, github: str, account: int) -> Session:
    """A team whose owner is signed in to the console, and that owner's Claude session."""
    _, owner_token = console.a_team(github)
    console.github.as_(account, github)
    client.sign_in()
    return Session(console.server, owner_token)


def ask(client: ConsoleClient, url: str, **asked: Any) -> dict[str, Any]:
    """A GET the console makes, which is expected to answer."""
    response = client.get(f"{url}?{urlencode({k: v for k, v in asked.items() if v is not None})}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def add(client: ConsoleClient, member_id: str, name: str, github: str | None = None) -> dict[str, Any]:
    """Add a member to the team through the console."""
    response = client.post_json("/api/members", {"member_id": member_id, "name": name, "github": github})
    assert response.status_code == 200, response.text
    added: dict[str, Any] = response.json()
    return added


def create(client: ConsoleClient, name: str) -> dict[str, Any]:
    """Create a project through the console."""
    response = client.post_json("/api/projects", {"name": name})
    assert response.status_code == 200, response.text
    created: dict[str, Any] = response.json()
    return created


def fetch_project(client: ConsoleClient, project_id: str) -> dict[str, Any]:
    """One project as the console shows it."""
    response = client.get(f"/api/projects/{project_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found
