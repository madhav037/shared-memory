"""`serve` sets up once, then runs several workers built without setup, sharing a budget of database connections."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import psycopg
import pytest

from shared_memory import app as app_module
from shared_memory import cli
from shared_memory.app import build_app, setup, worker_app
from shared_memory.config import Settings
from shared_memory.db import Database
from tests.support import REPO_ROOT, fresh_database


class StubEmbedder:
    def passages(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def query(self, text: str) -> list[float]:
        return [0.0]

    def tokens(self, words: list[str]) -> list[int]:
        return [1 for _ in words]


def tables(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()
    return {row[0] for row in rows}


def fresh_settings(name: str, tmp_path: Path, **more: Any) -> Settings:
    return Settings(
        database_url=fresh_database(name),
        memory_root=tmp_path / "memory",
        model_cache=REPO_ROOT / ".cache" / "fastembed",
        **more,
    )


# Settings


def test_workers_and_connections_default_to_two_and_forty() -> None:
    settings = Settings.from_env({})

    assert settings.workers == 2
    assert settings.database_connections == 40


def test_workers_and_connections_are_read_from_the_environment() -> None:
    settings = Settings.from_env({"SHARED_MEMORY_WORKERS": "3", "SHARED_MEMORY_DATABASE_CONNECTIONS": "60"})

    assert settings.workers == 3
    assert settings.database_connections == 60


def numbers(workers: int, connections: int) -> tuple[int, int]:
    settings = Settings("", Path("."), Path("."), workers=workers, database_connections=connections)
    return settings.pool_connections, settings.saving_connections


def test_the_connection_budget_is_split_among_the_workers_and_half_of_each_share_is_for_saves() -> None:
    assert numbers(2, 40) == (20, 10)  # what one worker had before there were several
    assert numbers(1, 40) == (40, 20)
    assert numbers(4, 40) == (10, 5)


def test_a_worker_keeps_at_least_four_connections() -> None:
    assert numbers(20, 40) == (4, 2)
    assert numbers(2, 2) == (4, 2)


def test_a_worker_count_below_one_is_one_worker() -> None:
    assert numbers(0, 40) == (40, 20)


def test_apart_connections_stay_within_the_saving_ones_and_leave_a_save_connection(tmp_path: Path) -> None:
    for workers, connections in ((2, 40), (10, 40), (20, 40)):
        settings = fresh_settings("shared_memory_split", tmp_path, workers=workers, database_connections=connections)
        db = Database(
            settings.database_url,
            settings.statement_timeout_seconds,
            pool_size=settings.pool_connections,
            saving_connections=settings.saving_connections,
        )
        try:
            assert db.apart_connections == (2 if settings.saving_connections > 2 else 1)
            assert db.apart_connections < settings.saving_connections
        finally:
            db.close()


# Setup and the worker factory


def test_setup_creates_the_schema_and_the_repository(tmp_path: Path) -> None:
    settings = fresh_settings("shared_memory_setup", tmp_path)

    setup(settings)

    assert {"teams", "members", "sections"} <= tables(settings.database_url)
    assert (settings.memory_root / ".git").exists()


def test_an_app_built_without_setup_creates_neither_schema_nor_repository(tmp_path: Path) -> None:
    settings = fresh_settings("shared_memory_no_setup", tmp_path)

    build_app(settings, embedder=StubEmbedder(), setup=False)

    assert tables(settings.database_url) == set()
    assert not (settings.memory_root / ".git").exists()


def test_an_app_built_without_setup_serves_a_database_that_was_set_up(tmp_path: Path) -> None:
    settings = fresh_settings("shared_memory_after_setup", tmp_path)
    setup(settings)

    app = build_app(settings, embedder=StubEmbedder(), setup=False)

    assert app is not None


def test_the_worker_factory_builds_from_the_environment_without_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[tuple[Settings, bool]] = []

    def build_app(settings: Settings, *args: Any, setup: bool = True, **kwargs: Any) -> Any:
        built.append((settings, setup))
        return "app"

    monkeypatch.setattr(app_module, "build_app", build_app)
    monkeypatch.setenv("SHARED_MEMORY_DATABASE_URL", "postgresql://elsewhere/db")
    monkeypatch.setenv("SHARED_MEMORY_WORKERS", "3")

    assert worker_app() == "app"  # type: ignore[comparison-overlap]

    [(settings, with_setup)] = built
    assert settings.database_url == "postgresql://elsewhere/db"
    assert settings.workers == 3
    assert with_setup is False


# serve


class Started:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[str] = []
        self.runs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        import uvicorn

        monkeypatch.setattr(app_module, "setup", lambda settings: self.events.append("setup"))
        monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: self._run(args, kwargs))

    def _run(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.events.append("run")
        self.runs.append((args, kwargs))


def serve(*arguments: str, workers: int = 2) -> int:
    settings = Settings("", Path("."), Path("."), workers=workers)
    return cli.run(["serve", *arguments], settings, io.StringIO())


def test_serve_sets_up_once_then_starts_the_configured_workers_from_the_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    started = Started(monkeypatch)

    assert serve("--port", "9000", workers=3) == 0

    assert started.events == ["setup", "run"]
    [(args, kwargs)] = started.runs
    assert args == ("shared_memory.app:worker_app",)
    assert kwargs["factory"] is True
    assert kwargs["workers"] == 3
    assert kwargs["port"] == 9000
    assert kwargs["host"] == "0.0.0.0"


def test_serve_workers_overrides_the_setting_and_reaches_the_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    started = Started(monkeypatch)

    serve("--workers", "4", workers=2)

    [(_, kwargs)] = started.runs
    assert kwargs["workers"] == 4


def test_the_workers_get_the_setting_serve_was_given(monkeypatch: pytest.MonkeyPatch) -> None:
    started = Started(monkeypatch)
    monkeypatch.setenv("SHARED_MEMORY_WORKERS", "2")  # put back when the test ends

    serve("--workers", "4", workers=2)

    assert started.runs
    import os

    assert os.environ["SHARED_MEMORY_WORKERS"] == "4"


def test_serve_with_one_worker_still_sets_up_then_builds_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    events: list[str] = []
    monkeypatch.setattr(app_module, "setup", lambda settings: events.append("setup"))

    def build_app(settings: Settings, *args: Any, setup: bool = True, **kwargs: Any) -> Any:
        events.append(f"build setup={setup}")
        return "app"

    def run(app: Any, **kwargs: Any) -> None:
        events.append(f"run {app} {sorted(kwargs)}")

    monkeypatch.setattr(app_module, "build_app", build_app)
    monkeypatch.setattr(uvicorn, "run", run)

    serve(workers=1)

    assert events == ["setup", "build setup=False", "run app ['host', 'port', 'timeout_keep_alive']"]

@pytest.mark.parametrize("workers", [1, 3])
def test_serve_keeps_idle_connections_open_longer_than_a_proxy_in_front_does(
    monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    started = Started(monkeypatch)
    if workers == 1:
        monkeypatch.setattr(app_module, "build_app", lambda *args, **kwargs: "app")

    serve(workers=workers)

    [(_, kwargs)] = started.runs
    assert kwargs["timeout_keep_alive"] == cli.KEEP_ALIVE_SECONDS > 120  # Caddy keeps its connections 2 minutes
