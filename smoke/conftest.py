"""Smoke tests with real Claude Code: run by hand or nightly with `uv run pytest smoke`, never with the unit tests.

They need Postgres (`docker compose up -d db`), Claude Code on PATH, and Claude Code signed in (or ANTHROPIC_API_KEY).
Each run costs a few cheap model calls; set SMOKE_CLAUDE_MODEL to try another model.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from smoke.claude import claude_executable
from tests.support import REPO_ROOT, RunningServer, Team, TestClock, fresh_database, new_team

Scope = dict[str, Any]


@dataclass(frozen=True)
class Request:
    path: str
    headers: dict[str, str]


class RequestLog:
    """Wraps the server's app and remembers the path and headers of every HTTP request it receives."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.requests: list[Request] = []

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = {name.decode().lower(): value.decode() for name, value in scope["headers"]}
            self.requests.append(Request(scope["path"], headers))
        await self.app(scope, receive, send)


class SlowApp:
    """A server that answers nothing for a long time."""

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await receive()
            await send({"type": "lifespan.startup.complete"})
            await receive()
            await send({"type": "lifespan.shutdown.complete"})
            return
        await asyncio.sleep(30)
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"{}"})


class SmokeServer(RunningServer):
    log: RequestLog


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if claude_executable() is None:
        pytest.exit("Claude Code is not installed: the claude command is not on PATH", returncode=2)


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SmokeServer]:
    settings = Settings(
        database_url=fresh_database("shared_memory_smoke"),
        memory_root=tmp_path_factory.mktemp("memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
    )
    clock = TestClock()
    log = RequestLog(build_app(settings, clock=clock, embedder=FastEmbedEmbedder(settings.model_cache)))
    with start_blocking_portal() as portal:
        running = SmokeServer(log, settings, clock, portal)
        running.log = log
        # A real server has long since loaded its search model; don't count that against the first hook.
        warm = new_team(running).owner()
        warm.in_project(warm.call("create_project", name="Warm-up")["project_id"]).call("search", query="warm up")
        try:
            yield running
        finally:
            running.stop()


@pytest.fixture(scope="session")
def slow_server_url() -> Iterator[str]:
    with start_blocking_portal() as portal:
        slow = RunningServer(SlowApp(), Settings("", REPO_ROOT, REPO_ROOT), TestClock(), portal)
        try:
            yield slow.url
        finally:
            slow.stop()


@pytest.fixture
def unreachable_server_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def team(server: SmokeServer) -> Team:
    return new_team(server)
