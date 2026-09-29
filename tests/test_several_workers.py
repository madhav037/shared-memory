"""Several workers save to one memory folder, with their turns held in Postgres (ADR-0013).

Two server instances built from the same settings share one database and one memory folder, so to Postgres and the
disk they are two workers. Saves take turns wherever they are handled, and what one worker saved reads fresh from the
other. The race tests (`test_concurrent_saves.py`, `test_turns_per_area.py`, `test_failed_saves.py`) also run with
their calls split across the two, through the `elsewhere` fixture.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable

from tests.support import RunningServer, Session, Team
from tests.test_failed_saves import uncommitted, word
from tests.test_turns_per_area import SLOW_TURN, all_at_once, note, slow_turns

__all__ = ["slow_turns"]  # a fixture these tests use


def on(server: RunningServer, session: Session) -> Session:
    """The same member and project, handled by another worker."""
    return dataclasses.replace(session, server=server)


def test_saves_into_one_area_sent_to_both_workers_still_take_turns(
    owner: Session, second_server: RunningServer, slow_turns: Callable[[], None]
) -> None:
    owner.call("remember", **note("Warm-up"))  # the member's folder exists, so only the area's turn is taken
    slow_turns()
    saves = 4

    results, took = all_at_once(
        [(owner if n % 2 == 0 else on(second_server, owner), "remember", note("One area")) for n in range(saves)]
    )

    assert len({result["path"] for result in results}) == saves
    assert took >= SLOW_TURN * saves, f"{saves} saves into one area took only {took:.1f} s"


def test_saves_into_different_areas_on_different_workers_overlap(
    owner: Session, dana: Session, cole: Session, second_server: RunningServer, slow_turns: Callable[[], None]
) -> None:
    sessions = [owner, on(second_server, dana), cole]
    for session in sessions:
        session.call("remember", **note("Warm-up"))
    slow_turns()

    results, took = all_at_once([(session, "remember", note("Overlapping")) for session in sessions])

    assert len({result["path"] for result in results}) == len(sessions)
    assert took < SLOW_TURN * len(sessions), f"{len(sessions)} saves took {took:.1f} s, as if one at a time"


def test_a_memory_saved_on_one_worker_reads_fresh_on_the_other(
    team: Team, owner: Session, second_server: RunningServer
) -> None:
    other = on(second_server, owner)
    first, second = word(), word()  # words only this memory holds, so a search for one finds it
    title = f"Fresh everywhere {uuid.uuid4().hex[:6]}"

    path = owner.call("remember", title=title, summary="As first saved.", type="gotcha", body=f"Said {first}.")["path"]
    assert reads(other, path, first) == ("As first saved.", f"Said {first}.")
    assert reads(owner, path, first) == ("As first saved.", f"Said {first}.")  # each worker has it parsed now

    other.call("edit_memory", path=path, summary="Edited on the other.", body=f"Now says {second}.")
    assert reads(owner, path, second) == ("Edited on the other.", f"Now says {second}.")

    owner.call("edit_memory", path=path, summary="Edited on the first.", body=f"Says {first} again.")
    assert reads(other, path, first) == ("Edited on the first.", f"Says {first} again.")
    assert uncommitted(team) == []


def reads(session: Session, path: str, word: str) -> tuple[str, str]:
    """A memory's summary and body as read, having checked that search and tree show the same summary."""
    memory = session.call("read", path=path)
    found = next(r for r in session.call("search", query=word)["results"] if r["path"] == path)
    listed = next(m for f in session.call("tree")["folders"] for m in f["memories"] if m["path"] == path)
    assert found["summary"] == listed["summary"] == memory["summary"]
    return memory["summary"], memory["body"].strip()
