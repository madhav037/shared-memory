"""A save cut off mid-turn, by the worker handling it dying, is put back by the next save in its area (ADR-0013).

A worker is killed the way a real one dies: its save's database connection is terminated from outside, which releases
its turns and rolls back its transaction, and nothing more of the save runs, so nothing of it is undone. Before it
writes any file a save records a marker of the paths it may touch; the next save to take that area's turn finds it,
puts those paths back to what main holds, and indexes them again. Here the next save is handled by the other worker.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

import psycopg
import pytest

from shared_memory.store import MemoryStore
from tests.support import RunningServer, Session, Team
from tests.test_failed_saves import files_named, head, indexed, main_lock, remember, uncommitted, word
from tests.test_several_workers import on

When = Literal["before main moves", "after main moves"]
Dies = Callable[[When], None]


class WorkerDied(Exception):
    """What the dying save's thread raises once its connection is gone, so it does nothing more."""


def kill_saving_connections(settings_url: str) -> int:
    """Terminate every connection holding a save's turns, as Postgres does when the worker holding it dies."""
    with psycopg.connect(settings_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT pg_terminate_backend(pid) FROM (SELECT DISTINCT pid FROM pg_locks"
            " WHERE locktype = 'advisory' AND granted AND pid <> pg_backend_pid()) AS holders"
        ).fetchall()
    return len(rows)


@pytest.fixture
def dies(team: Team, monkeypatch: pytest.MonkeyPatch) -> Dies:
    """Call it to make the next save's worker die at that point: just before the save moves main, or just after."""
    armed: list[When] = []
    dead: set[int] = set()
    commit, undo = MemoryStore._commit, MemoryStore._undo

    def dying_commit(self: MemoryStore, *args: Any, **kwargs: Any) -> Any:
        if not armed:
            return commit(self, *args, **kwargs)
        when = armed.pop()
        if when == "after main moves":
            commit(self, *args, **kwargs)
        assert kill_saving_connections(team.server.settings.database_url) >= 1
        dead.add(threading.get_ident())
        raise WorkerDied("the worker died")

    def dead_undo(self: MemoryStore, *args: Any, **kwargs: Any) -> Any:
        if threading.get_ident() in dead:
            dead.discard(threading.get_ident())
            return None  # a dead worker undoes nothing and clears no marker
        return undo(self, *args, **kwargs)

    monkeypatch.setattr(MemoryStore, "_commit", dying_commit)
    monkeypatch.setattr(MemoryStore, "_undo", dead_undo)
    return armed.append


def markers(team: Team) -> list[str]:
    """Every path the markers left in the team's turns name."""
    with psycopg.connect(team.server.settings.database_url) as conn:
        rows = conn.execute("SELECT paths FROM save_markers WHERE team = %s", (team.code,)).fetchall()
    return sorted(path for row in rows for path in row[0])


def listed(session: Session) -> list[str]:
    return [memory["path"] for folder in session.call("tree")["folders"] for memory in folder["memories"]]


def found(session: Session, word: str) -> list[str]:
    return [hit["path"] for hit in session.call("search", query=word)["results"]]


def dangling(team: Team) -> list[str]:
    """Every link in the team's indexes to a memory or folder that isn't there."""
    folder = team.server.settings.memory_root / team.code
    return [
        f"{index.relative_to(folder).as_posix()} -> {target}"
        for index in folder.rglob("index.md")
        for target in re.findall(r"\]\(([^)]+)\)", index.read_text(encoding="utf-8"))
        if not (index.parent / Path(target)).exists()
    ]


@pytest.fixture
def warnings(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.WARNING, logger="shared_memory"):
        yield caplog


def test_a_new_memory_cut_off_before_main_moved_is_removed_by_the_next_save_in_its_area(
    team: Team, owner: Session, second_server: RunningServer, dies: Dies, warnings: pytest.LogCaptureFixture
) -> None:
    tag, unique = uuid.uuid4().hex[:8], word()
    before = head(team)
    dies("before main moves")

    owner.refusal("remember", title=f"Cut off {tag}", summary="Half saved.", type="gotcha", body=unique)

    # The dead worker's first save in its area left its memory, its folders and their indexes on disk, uncommitted.
    assert head(team) == before
    assert files_named(team, tag) != []
    assert uncommitted(team) != []
    left = markers(team)
    assert any(tag in path for path in left)

    other = on(second_server, owner)
    saved = remember(other, f"Next {uuid.uuid4().hex[:6]}", word())

    assert files_named(team, tag) == []
    assert uncommitted(team) == []
    assert markers(team) == []
    assert indexed(team, unique) == []
    for session in (owner, other):
        assert listed(session) == [saved]
        assert not [path for path in found(session, unique) if tag in path]
    assert any(tag in record.getMessage() for record in warnings.records if record.levelno == logging.WARNING)


def test_an_edit_cut_off_before_main_moved_is_put_back_by_the_next_save_in_its_area(
    team: Team, owner: Session, second_server: RunningServer, dies: Dies
) -> None:
    kept, changed = word(), word()
    path = remember(owner, f"Edited {uuid.uuid4().hex[:6]}", kept)
    dies("before main moves")

    owner.refusal("edit_memory", path=path, summary="Half edited.", body=changed)
    assert uncommitted(team) != []

    other = on(second_server, owner)
    remember(other, f"Next {uuid.uuid4().hex[:6]}", word())

    assert uncommitted(team) == []
    assert markers(team) == []
    for session in (owner, other):
        memory = session.call("read", path=path)
        assert (memory["summary"], memory["body"].strip()) == ("What was learned.", kept)
    assert indexed(team, kept) == [path]
    assert indexed(team, changed) == []


def test_a_new_memory_cut_off_after_main_moved_is_indexed_by_the_next_save_in_its_area(
    team: Team, owner: Session, second_server: RunningServer, dies: Dies
) -> None:
    remember(owner, f"Already there {uuid.uuid4().hex[:6]}", word())
    tag, unique = uuid.uuid4().hex[:8], word()
    before = head(team)
    dies("after main moves")

    owner.refusal("remember", title=f"Committed {tag}", summary="In main, not indexed.", type="gotcha", body=unique)

    # main holds the memory, but the database never took the save: the search index is missing it.
    assert head(team) != before
    assert uncommitted(team) == []
    assert indexed(team, unique) == []
    (file,) = files_named(team, tag)
    path = file.relative_to(team.server.settings.memory_root / team.code).as_posix()

    other = on(second_server, owner)
    remember(other, f"Next {uuid.uuid4().hex[:6]}", word())

    assert uncommitted(team) == []
    assert markers(team) == []
    assert indexed(team, unique) == [path]
    for session in (owner, other):
        assert path in listed(session)
        assert path in found(session, unique)
        assert session.call("read", path=path)["summary"] == "In main, not indexed."


def test_an_edit_cut_off_after_main_moved_is_indexed_as_main_holds_it(
    team: Team, owner: Session, second_server: RunningServer, dies: Dies
) -> None:
    kept, changed = word(), word()
    path = remember(owner, f"Edited {uuid.uuid4().hex[:6]}", kept)
    dies("after main moves")

    owner.refusal("edit_memory", path=path, summary="Edited in main.", body=changed)
    assert indexed(team, kept) == [path]

    remember(on(second_server, owner), f"Next {uuid.uuid4().hex[:6]}", word())

    assert uncommitted(team) == []
    assert markers(team) == []
    assert indexed(team, changed) == [path]
    assert indexed(team, kept) == []
    assert owner.call("read", path=path)["summary"] == "Edited in main."


def test_a_save_in_another_area_leaves_a_cut_off_save_alone(
    team: Team, owner: Session, dana: Session, second_server: RunningServer, dies: Dies
) -> None:
    # Both areas' folders exist, so neither save changes the folders the areas share.
    remember(owner, f"Owner's first {uuid.uuid4().hex[:6]}", word())
    remember(dana, f"Dana's first {uuid.uuid4().hex[:6]}", word())
    tag = uuid.uuid4().hex[:8]
    dies("before main moves")
    owner.refusal("remember", title=f"Cut off {tag}", summary="Half saved.", type="gotcha", body=word())
    left = markers(team)

    saved = remember(on(second_server, dana), f"Dana's next {uuid.uuid4().hex[:6]}", word())

    assert saved in listed(dana)
    assert markers(team) == left
    assert files_named(team, tag) != []

    remember(on(second_server, owner), f"Owner's next {uuid.uuid4().hex[:6]}", word())
    assert files_named(team, tag) == []
    assert uncommitted(team) == []
    assert markers(team) == []


def test_saves_that_land_or_are_undone_leave_no_marker(team: Team, owner: Session) -> None:
    path = remember(owner, f"Marked {uuid.uuid4().hex[:6]}", word())
    owner.call("edit_memory", path=path, body=word())
    assert markers(team) == []

    lock = main_lock(team)
    lock.write_text("")
    try:
        owner.refusal("edit_memory", path=path, body=word())
    finally:
        lock.unlink()
    assert markers(team) == []

    owner.call("delete_memory", path=path)
    assert markers(team) == []
    assert uncommitted(team) == []


def test_repair_that_removes_a_cut_off_area_folder_takes_it_out_of_the_shared_index(
    team: Team, owner: Session, dana: Session, second_server: RunningServer, dies: Dies
) -> None:
    # The owner's first save in their area is cut off: their area's folder is left on disk, uncommitted.
    tag = uuid.uuid4().hex[:8]
    dies("before main moves")
    owner.refusal("remember", title=f"Cut off {tag}", summary="Half saved.", type="gotcha", body=word())
    (file,) = files_named(team, tag)
    path = file.relative_to(team.server.settings.memory_root / team.code).as_posix()

    # Dana's first save changes the folders the areas share, and lists them as they stand: the owner's folder too.
    remember(on(second_server, dana), f"Dana's first {uuid.uuid4().hex[:6]}", word())
    assert uncommitted(team) != []

    # The owner's next save in their area repairs it, even though that save is itself refused.
    owner.refusal("delete_memory", path=path)

    assert files_named(team, tag) == []
    assert dangling(team) == []
    assert uncommitted(team) == []
    assert markers(team) == []
