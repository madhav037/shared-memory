"""Test harness: a running server and sessions that talk to it like Claude Code does."""

from __future__ import annotations

import io
import threading
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import httpx2
import uvicorn
from anyio.from_thread import BlockingPortal
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from shared_memory import cli
from shared_memory.config import Settings


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
    def __init__(self, app: Any, settings: Settings, clock: TestClock, portal: BlockingPortal) -> None:
        self.settings = settings
        self.clock = clock
        self.portal = portal
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
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

    def run_cli(self, *argv: str) -> str:
        out = io.StringIO()
        code = cli.run(list(argv), settings=self.settings, out=out)
        if code != 0:
            raise RuntimeError(f"command {argv} failed: {out.getvalue()}")
        return out.getvalue()


@dataclass
class Session:
    """One Claude Code session of a member, as the server sees it."""

    server: RunningServer
    token: str | None
    project: str | None = None
    repository: str | None = None

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
        return Session(self.server, self.token, project, repository)

    def call(self, tool: str, **arguments: Any) -> Any:
        """Call an MCP tool; return its structured result or raise ToolRefused with its message."""
        return self.server.portal.call(self._call, tool, arguments)

    async def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        async with AsyncExitStack() as stack:
            http = await stack.enter_async_context(httpx2.AsyncClient(headers=self.headers(), timeout=60))
            transport = streamable_http_client(f"{self.server.url}/mcp", http_client=http)
            client = await stack.enter_async_context(Client(transport))
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

    def refusal(self, tool: str, **arguments: Any) -> str:
        """Call a tool that is expected to be refused; return the refusal message."""
        try:
            self.call(tool, **arguments)
        except ToolRefused as refused:
            return str(refused)
        raise AssertionError(f"{tool} was not refused")

    def _hook(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {"session_id": "test-session", "cwd": "/work/app", "hook_event_name": event, **payload}
        response = httpx.post(f"{self.server.url}/hooks/{event}", json=body, headers=self.headers(), timeout=60)
        assert response.status_code == 200, response.text
        data: dict[str, Any] = response.json()
        return data

    def start(self) -> dict[str, Any]:
        """Fire the session-start hook and return its hook output."""
        return self._hook("session-start", {"source": "startup"})

    def prompt(self, text: str) -> dict[str, Any]:
        """Fire the prompt-submitted hook and return its hook output."""
        return self._hook("prompt-submitted", {"prompt": text})


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
