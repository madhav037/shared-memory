from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import RunningServer, Team, TestClock, new_team

ADMIN_URL = os.environ.get("SHARED_MEMORY_TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5433/postgres")
TEST_DB = "shared_memory_test"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _fresh_database() -> str:
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.OperationalError as error:
        pytest.exit(f"Postgres is not reachable ({error}). Start it with: docker compose up -d db", returncode=2)
    return ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = Settings(
        database_url=_fresh_database(),
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
