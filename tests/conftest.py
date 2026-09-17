from __future__ import annotations

from collections.abc import Iterator

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import REPO_ROOT, RunningServer, Team, TestClock, fresh_database, new_team


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
