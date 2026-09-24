"""Test harness: a running server and sessions that talk to it the way a coding agent does."""

from __future__ import annotations

import io
import os
import threading
import time
import uuid
from collections.abc import AsyncIterator
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


def fresh_database(name: str) -> str:
    """Drop and recreate a database on the test Postgres; return its URL."""
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
    output = server.run_cli("setup", "--team", code, "--owner-employee-id", "owner-1", "--owner-name", "Olive Owner")
    token = next(line.split(":", 1)[1].strip() for line in output.splitlines() if line.startswith("Owner personal token:"))
    return Team(server, code, token)


def member(team: Team, project: str, employee_id: str, name: str) -> Session:
    """A session for a member added to the team, working in one project."""
    added = team.owner().call("add_member", employee_id=employee_id, name=name)
    return Session(team.server, added["personal_token"], project, "billing-api")


class FakeGitHub:
    """Stands in for GitHub's sign-in, so no test touches the real one.

    It signs everyone in as whichever account it has been told to return, which is how a test chooses who is at the
    keyboard. The browser journeys change that account through `POST /as-account`.
    """

    def __init__(self, portal: BlockingPortal, settings: Settings, port: int = 0) -> None:
        self.account_id = 1
        self.login = "olive"

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
            self.as_(int(body["id"]), str(body["login"]))
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

    def as_(self, account_id: int, login: str) -> None:
        """Whoever signs in next is this GitHub account."""
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
            "setup", "--team", code, "--owner-employee-id", "E1001", "--owner-name", "Olive Owner",
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


def add(client: ConsoleClient, employee_id: str, name: str, github: str | None = None) -> dict[str, Any]:
    """Add a member to the team through the console."""
    response = client.post_json("/api/members", {"employee_id": employee_id, "name": name, "github": github})
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
