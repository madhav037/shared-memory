"""Saves happen one at a time. A save waiting its turn must not hold a worker thread that reads and hooks need."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Iterator

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import RunningServer, added_context, new_team, promote_now

# More saves than the server has worker threads (40), so saves that each held a thread while waiting would take them all.
QUEUED_SAVES = 60
SECONDS_PER_SAVE = 0.3

MONEY = {
    "title": "Money amounts",
    "summary": "Money is stored as integer cents.",
    "type": "convention",
    "body": "All money amounts are stored as integer cents, never floats.",
}


class SlowSavingEmbedder(FastEmbedEmbedder):
    """Indexing a saved memory is slow, so saves pile up behind each other; searching stays fast."""

    def passages(self, texts: list[str]) -> list[list[float]]:
        time.sleep(SECONDS_PER_SAVE)
        return super().passages(texts)


@pytest.fixture
def slow_saving_server(server: RunningServer, tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = dataclasses.replace(server.settings, memory_root=tmp_path_factory.mktemp("slow-saving-memory"))
    app = build_app(settings, clock=server.clock, embedder=SlowSavingEmbedder(settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, server.clock, portal)
        try:
            yield running
        finally:
            running.stop()


def test_a_read_and_a_hook_answer_promptly_while_many_saves_wait(slow_saving_server: RunningServer) -> None:
    team = new_team(slow_saving_server)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    owner = team.owner().in_project(project, "billing-api")
    money = promote_now(owner, MONEY)

    saves = [
        owner.call_soon(
            "remember",
            title=f"Queued note {number}",
            summary=f"Note number {number}.",
            type="gotcha",
            body=f"Note number {number} was saved while many other saves waited their turn.",
        )
        for number in range(QUEUED_SAVES)
    ]
    time.sleep(1.5)

    started = time.monotonic()
    found = owner.call("search", query="how are money amounts stored?")
    read_took = time.monotonic() - started
    started = time.monotonic()
    recalled = added_context(owner.prompt("store the refund amount in the database"))
    hook_took = time.monotonic() - started
    still_waiting = sum(not save.done() for save in saves)

    assert still_waiting > 0
    assert read_took < 3, f"search took {read_took:.1f} s behind {still_waiting} waiting saves"
    assert hook_took < 3, f"the prompt hook took {hook_took:.1f} s behind {still_waiting} waiting saves"
    assert money in [result["path"] for result in found["results"]]
    assert money in recalled
    paths = {save.result(timeout=120)["path"] for save in saves}
    assert len(paths) == QUEUED_SAVES
