"""A save builds its commit in-process and moves main last, with a compare-and-swap (#157).

No git process runs while a member saves, and a save that finds main moved while it built its commit builds again on
the new main, so both land.
"""

from __future__ import annotations

import subprocess
import uuid
from typing import Any

import pygit2
import pytest

import shared_memory.store as store
from tests.support import Session, Team

# The real Popen, so git the test runs itself is unaffected while saving is watched.
_Popen = subprocess.Popen


def git(team: Team, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), *args], capture_output=True, text=True, check=True
    ).stdout


def test_saving_runs_no_git_process(team: Team, owner: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[list[str]] = []

    class Recording(_Popen):  # type: ignore[type-arg]
        def __init__(self, args: Any, *rest: Any, **options: Any) -> None:
            started.append([str(arg) for arg in args] if isinstance(args, (list, tuple)) else [str(args)])
            super().__init__(args, *rest, **options)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    path = owner.call(
        "remember", title=f"In process {uuid.uuid4().hex[:6]}", summary="No git.", type="gotcha", body="b"
    )["path"]
    monkeypatch.undo()

    assert not [args for args in started if any("git" in arg for arg in args[:1])]
    assert f"{team.code}/{path}" in git(team, "show", "--name-only", "--format=", "HEAD").split()
    email, committer, trailer = git(
        team, "log", "-1", "--format=%ae%n%cn%n%(trailers:key=Coding-Agent,valueonly)"
    ).splitlines()[:3]
    assert email.endswith("@members.shared-memory.invalid")
    assert committer == "Shared Memory"
    assert trailer.strip()


def test_a_save_that_finds_main_moved_builds_again_on_it_and_both_land(
    team: Team, owner: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = f"elsewhere-{uuid.uuid4().hex[:8]}/note.md"
    move_main = store._move_main
    intruded: list[pygit2.Oid | None] = []

    def moved_first(repository: pygit2.Repository, expected: pygit2.Oid | None, commit: pygit2.Oid, why: str) -> bool:
        if not intruded:
            intruded.append(None)
            # Another save moves main between this save building its commit and moving main to it.
            blob = repository.create_blob(b"Saved elsewhere.\n")
            landed = store._land(repository, {elsewhere: blob}, "Elsewhere\n", pygit2.Signature(*store.SERVER))
            assert landed is not None
            intruded[0] = landed.commit
        return move_main(repository, expected, commit, why)

    monkeypatch.setattr(store, "_move_main", moved_first)
    title = f"Retried {uuid.uuid4().hex[:6]}"
    path = owner.call("remember", title=title, summary="Lands on the new main.", type="gotcha", body="b")["path"]

    assert git(team, "rev-parse", "HEAD~1").strip() == str(intruded[0])
    assert git(team, "log", "-1", "--format=%s").strip() == f"Remember: {title}"
    committed = git(team, "ls-tree", "-r", "--name-only", "HEAD").split("\n")
    assert f"{team.code}/{path}" in committed
    assert elsewhere in committed
    assert owner.call("read", path=path)["title"] == title
