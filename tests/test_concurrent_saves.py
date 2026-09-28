"""Parallel sessions changing the same memory at once, the way a member's subagents or several members would.

Each race is run a number of times: a lost change only shows when the two saves interleave, which they don't always.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from tests.support import Session, Team, ToolRefused

TRIALS = 8


def at_once(*calls: Callable[[], Any]) -> list[Any]:
    """Run the calls at the same instant; each result is its return value or the ToolRefused it raised."""
    start = threading.Barrier(len(calls))

    def run(call: Callable[[], Any]) -> Any:
        start.wait()
        try:
            return call()
        except ToolRefused as refused:
            return refused

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(run, calls))


def remember(session: Session, title: str, type: str = "convention", body: str = "original body") -> str:
    path: str = session.call("remember", title=f"{title} {uuid.uuid4().hex[:6]}", summary="original", type=type, body=body)[
        "path"
    ]
    return path


def test_two_edits_of_different_fields_both_land(owner: Session) -> None:
    for trial in range(TRIALS):
        path = remember(owner, "Edited twice")

        outcomes = at_once(
            lambda: owner.call("edit_memory", path=path, summary=f"summary {trial}"),
            lambda: owner.call("edit_memory", path=path, body=f"body {trial}"),
        )
        memory = owner.call("read", path=path)

        assert not [o for o in outcomes if isinstance(o, ToolRefused)], outcomes
        assert (memory["summary"], memory["body"].strip()) == (f"summary {trial}", f"body {trial}")


def test_an_edit_racing_a_delete_never_brings_the_memory_back(owner: Session) -> None:
    for _ in range(TRIALS):
        path = remember(owner, "Deleted while edited", type="gotcha")

        deleted, edited = at_once(
            lambda: owner.call("delete_memory", path=path),
            lambda: owner.call("edit_memory", path=path, body="edited"),
        )

        assert deleted == {"deleted": path}
        assert not isinstance(edited, ToolRefused) or "no memory" in str(edited), edited
        assert "no memory" in owner.refusal("read", path=path)


def test_a_memory_promoted_by_several_sessions_at_once_is_promoted_once(team: Team) -> None:
    for trial in range(TRIALS // 2):
        # A project of its own each time, so the memory promoted last time isn't a similar memory this time.
        owner = team.owner().in_project(team.owner().call("create_project", name=f"Promoting {trial}")["project_id"])
        path = remember(owner, "Promoted at once", type="architecture")

        outcomes = at_once(*[lambda: owner.call("promote", path=path, level="project")] * 3)
        promoted = [o for o in outcomes if isinstance(o, dict) and o.get("status") == "promoted"]
        shared = owner.call("tree", level="project")["folders"]

        assert len(promoted) == 1, outcomes
        assert all("no memory" in str(o) for o in outcomes if isinstance(o, ToolRefused)), outcomes
        assert [m["path"] for folder in shared for m in folder["memories"]] == [promoted[0]["path"]]


def while_saving(save: Callable[[], None], look: Callable[[], Any], lookers: int = 3) -> tuple[Any, list[str]]:
    """Run save once while several sessions keep calling look; return what save did and every refusal look got."""
    done = threading.Event()

    def saving() -> None:
        try:
            save()
        finally:
            done.set()

    def looking() -> list[str]:
        refusals = []
        while not done.is_set():
            try:
                look()
            except ToolRefused as refused:
                refusals.append(str(refused))
        return refusals

    saved, *looked = at_once(saving, *[looking] * lookers)
    return saved, [refusal for refusals in looked for refusal in refusals]


def test_a_memory_read_while_it_is_being_saved_is_never_half_written(owner: Session) -> None:
    path = remember(owner, "Read while saved", body="word " * 500)

    def edit() -> None:
        for n in range(20):
            owner.call("edit_memory", path=path, body=f"version {n} " + "word " * 500)

    saved, refusals = while_saving(edit, lambda: owner.call("read", path=path))

    assert (saved, refusals) == (None, [])


def test_listing_memory_while_memories_are_deleted_never_fails(owner: Session) -> None:
    paths = [remember(owner, "Listed while deleted", type="gotcha") for _ in range(20)]
    folder = paths[0].rsplit("/", 1)[0]

    def delete() -> None:
        for path in paths:
            owner.call("delete_memory", path=path)

    def browse() -> None:
        owner.call("tree")
        owner.call("list", folder=folder)

    saved, refusals = while_saving(delete, browse)

    assert (saved, refusals) == (None, [])
