from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import REPO_ROOT, Console, ConsoleClient, FakeGitHub, RunningServer, Team, TestClock, fresh_database, new_team


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = Settings(
        database_url=fresh_database("shared_memory_test"),
        memory_root=tmp_path_factory.mktemp("memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
    )
    clock = TestClock()
    app = build_app(settings, clock=clock, embedder=FastEmbedEmbedder(settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, clock, portal)
        try:
            yield running
        finally:
            running.stop()


@pytest.fixture
def team(server: RunningServer) -> Team:
    server.clock.now = TestClock().now
    return new_team(server)


@pytest.fixture(scope="module")
def console(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Console]:
    with start_blocking_portal() as portal:
        memory = tmp_path_factory.mktemp("console-memory")
        github = FakeGitHub(portal, Settings("", Path(memory), Path(memory)))
        clock = TestClock()
        settings = Settings(
            database_url=fresh_database("shared_memory_console"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=github.url,
            github_api_url=github.url,
        )
        server = RunningServer(build_app(settings, clock=clock), settings, clock, portal)
        try:
            yield Console(server, github, clock)
        finally:
            server.stop()
            github.stop()


@pytest.fixture
def signed_out(console: Console) -> Iterator[ConsoleClient]:
    console.clock.now = TestClock().now
    client = console.client()
    try:
        yield client
    finally:
        client.close()
