"""The search model and Postgres stay within bounds: a query is embedded once, and a stalled database fails requests
instead of freezing them."""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.embeddings import CachedQueries, FastEmbedEmbedder
from tests.support import RunningServer, Session, ToolRefused, new_team


class CountingEmbedder(FastEmbedEmbedder):
    """The real model, counting the queries it is asked to embed."""

    def __init__(self, cache_dir: Path) -> None:
        super().__init__(cache_dir)
        self.queries: list[str] = []

    def query(self, text: str) -> list[float]:
        self.queries.append(text)
        return super().query(text)


@pytest.fixture
def counted(server: RunningServer, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Session, CountingEmbedder]]:
    settings = dataclasses.replace(server.settings, memory_root=tmp_path_factory.mktemp("counted-memory"))
    embedder = CountingEmbedder(settings.model_cache)
    with start_blocking_portal() as portal:
        running = RunningServer(build_app(settings, clock=server.clock, embedder=embedder), settings, server.clock, portal)
        try:
            team = new_team(running)
            project = team.owner().call("create_project", name="Billing")["project_id"]
            yield team.owner().in_project(project), embedder
        finally:
            running.stop()


def test_a_repeated_search_does_not_embed_its_query_again(counted: tuple[Session, CountingEmbedder]) -> None:
    session, embedder = counted
    session.call("remember", title="Money amounts", summary="Integer cents.", type="convention", body="Cents, never floats.")

    first = session.call("search", query="how is money stored")
    again = session.call("search", query="how is money stored")
    session.call("search", query="how do retries work")

    assert again == first
    assert embedder.queries == ["how is money stored", "how do retries work"]


def test_a_prompt_recalled_twice_is_embedded_once(counted: tuple[Session, CountingEmbedder]) -> None:
    session, embedder = counted

    session.prompt("store the refund amount in the database")
    session.prompt("store the refund amount in the database")

    assert embedder.queries.count("store the refund amount in the database") == 1


class Recorder:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]

    def query(self, text: str) -> list[float]:
        self.asked.append(text)
        return [float(len(text))]

    def tokens(self, words: list[str]) -> list[int]:
        return [1 for _ in words]


def test_the_query_cache_forgets_the_least_recently_used_query_past_its_bound() -> None:
    inner = Recorder()
    cached = CachedQueries(inner, size=2)

    for text in ["a", "bb", "a", "ccc", "a", "bb"]:
        cached.query(text)

    # "bb" was the least recently used when "ccc" arrived, so it had to be embedded again; "a" never was.
    assert inner.asked == ["a", "bb", "ccc", "bb"]
    assert cached.query("a") == [1.0]


def test_passages_are_never_cached() -> None:
    inner = Recorder()
    cached = CachedQueries(inner, size=2)

    assert cached.passages(["a", "bb"]) == [[1.0], [2.0]]
    assert cached.passages([]) == []


@pytest.fixture
def impatient(server: RunningServer, tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = dataclasses.replace(
        server.settings, memory_root=tmp_path_factory.mktemp("impatient-memory"), statement_timeout_seconds=1
    )
    with start_blocking_portal() as portal:
        running = RunningServer(build_app(settings, clock=server.clock), settings, server.clock, portal)
        try:
            yield running
        finally:
            running.stop()


def test_a_stalled_database_fails_the_request_instead_of_freezing_it(impatient: RunningServer) -> None:
    team = new_team(impatient)
    owner = team.owner()
    stall = psycopg.connect(impatient.settings.database_url)
    stall.execute("LOCK TABLE tokens IN ACCESS EXCLUSIVE MODE")
    release = threading.Timer(8, stall.rollback)
    release.start()
    try:
        started = time.monotonic()
        with pytest.raises(ToolRefused):
            owner.call("create_project", name="Billing")
        assert time.monotonic() - started < 5
    finally:
        release.cancel()
        stall.rollback()
        stall.close()

    assert owner.call("create_project", name="Billing")["name"] == "Billing"
