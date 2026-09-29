"""A save's turn runs no embedding model: a memory's vectors are computed before the save waits for its turn."""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.embeddings import FastEmbedEmbedder
from shared_memory.store import MemoryStore
from tests.support import RunningServer, new_team, promote_now

NOTE = {
    "title": "Refund rounding",
    "summary": "Refunds round half up to the cent.",
    "type": "convention",
    "body": "Refund amounts round half up to the nearest cent before they are sent to the payment provider.",
}

_in_turn = threading.local()


class WatchingEmbedder(FastEmbedEmbedder):
    """Records every text embedded while the calling thread holds a save's turn."""

    inside_a_turn: list[str] = []

    def passages(self, texts: list[str]) -> list[list[float]]:
        if getattr(_in_turn, "held", False):
            self.inside_a_turn.extend(texts)
        return super().passages(texts)


@pytest.fixture
def watched_server(
    server: RunningServer, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[RunningServer, WatchingEmbedder]]:
    original = MemoryStore._one_save_at_a_time

    @contextmanager
    def watched(self: MemoryStore) -> Iterator[None]:
        with original(self):
            _in_turn.held = True
            try:
                yield
            finally:
                _in_turn.held = False

    monkeypatch.setattr(MemoryStore, "_one_save_at_a_time", watched)
    settings = dataclasses.replace(server.settings, memory_root=tmp_path_factory.mktemp("watched-memory"))
    embedder = WatchingEmbedder(settings.model_cache)
    embedder.inside_a_turn = []
    app = build_app(settings, clock=server.clock, embedder=embedder)
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, server.clock, portal)
        try:
            yield running, embedder
        finally:
            running.stop()


def test_remember_edit_and_promote_embed_nothing_inside_the_turn(
    watched_server: tuple[RunningServer, WatchingEmbedder],
) -> None:
    running, embedder = watched_server
    team = new_team(running)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    owner = team.owner().in_project(project, "billing-api")

    path = owner.call("remember", **NOTE)["path"]
    found = owner.call("search", query="how do refunds round?")
    assert path in [result["path"] for result in found["results"]]

    owner.call("edit_memory", path=path, body="Refund amounts round half even to the cent, as the provider does.")
    found = owner.call("search", query="refunds round half even provider")
    assert path in [result["path"] for result in found["results"]]

    promoted = promote_now(owner, {**NOTE, "title": "Tax rounding", "summary": "Tax rounds down."})
    found = owner.call("search", query="tax rounds down")
    assert promoted in [result["path"] for result in found["results"]]

    assert embedder.inside_a_turn == []
