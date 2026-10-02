"""Locks on files: a session takes one before its coding agent edits a file, and another session is refused."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from shared_memory.locks import NEVER_LOCK, Locks
from tests.support import Console, ConsoleClient, RunningServer, Session, Team, ToolRefused
from tests.test_restricted_projects import restricted

FILE = "src/webhooks/retry.py"


def take(session: Session, path: str = FILE, **more: Any) -> dict[str, Any]:
    taken: dict[str, Any] = session.call("take_lock", path=path, session=session.identifier, **more)
    return taken


def refused(session: Session, path: str = FILE, **more: Any) -> str:
    return session.refusal("take_lock", path=path, session=session.identifier, **more)


def release(session: Session, path: str = FILE, **more: Any) -> dict[str, Any]:
    released: dict[str, Any] = session.call("release_lock", path=path, session=session.identifier, **more)
    return released


def at(moment: str) -> datetime:
    return datetime.fromisoformat(moment)


# Taking a lock


def test_a_session_takes_a_lock_and_taking_it_again_moves_when_it_was_last_used(team: Team, dana: Session) -> None:
    first = take(dana)
    team.server.clock.advance(minutes=5)

    again = take(dana)

    assert first["locked"] is True
    assert (first["repository"], first["path"]) == ("billing-api", FILE)
    assert again["locked"] is True
    assert again["taken_at"] == first["taken_at"] == first["last_used_at"]
    assert (at(again["last_used_at"]) - at(first["last_used_at"])).total_seconds() == 300


def test_another_members_session_is_refused_and_told_who_holds_the_file(
    team: Team, dana: Session, cole: Session
) -> None:
    taken = take(dana.as_agent("claude-code"))
    team.server.clock.advance(minutes=5)

    refusal = refused(cole)

    assert "Dana Dev (emp-2)" in refusal
    assert "Claude Code" in refusal
    assert f"billing-api:{FILE}" in refusal
    assert "5 minutes ago" in refusal
    assert taken["last_used_at"] in refusal
    assert "stated no activity" in refusal


def test_the_same_members_other_session_is_refused_too(dana: Session) -> None:
    second = dana.as_session("second-session")
    take(dana)

    refusal = refused(second)

    assert "Dana Dev (emp-2)" in refusal
    assert take(dana)["locked"] is True


def test_the_same_path_in_two_repositories_of_one_project_is_two_locks(
    project: str, dana: Session, cole: Session
) -> None:
    take(dana)

    by_naming_it = take(cole, repository="billing-web")
    from_within_it = take(cole.in_project(project, "billing-jobs").as_session("jobs-session"))

    assert (by_naming_it["locked"], by_naming_it["repository"]) == (True, "billing-web")
    assert (from_within_it["locked"], from_within_it["repository"]) == (True, "billing-jobs")
    assert "Dana Dev" in refused(cole), "billing-api's file is still Dana's"


def test_the_same_path_in_two_projects_is_two_locks(team: Team, dana: Session, cole: Session) -> None:
    checkout = team.owner().call("create_project", name="Checkout")["project_id"]
    take(dana)

    elsewhere = take(cole.in_project(checkout, "billing-api"))

    assert elsewhere["locked"] is True
    assert "Dana Dev" in refused(cole)


def test_two_sessions_racing_for_one_file_exactly_one_holds_it(
    dana: Session, cole: Session, elsewhere: Callable[[Session], Session]
) -> None:
    for attempt in range(5):
        path = f"src/webhooks/attempt_{attempt}.py"
        arguments = {"path": path, "session": "test-session"}
        racing = {
            "Dana Dev": dana.call_soon("take_lock", **arguments),
            "Cole Coder": elsewhere(cole).call_soon("take_lock", **arguments),
        }

        won, lost = [], []
        for name, future in racing.items():
            try:
                future.result(timeout=30)
                won.append(name)
            except ToolRefused as refusal:
                lost.append(str(refusal))

        assert len(won) == 1
        assert len(lost) == 1
        assert won[0] in lost[0]


def test_a_lock_taken_through_one_worker_refuses_a_session_calling_through_another(
    dana: Session, cole: Session, second_server: RunningServer
) -> None:
    take(dana)

    refusal = refused(dataclasses.replace(cole, server=second_server))

    assert "Dana Dev (emp-2)" in refusal
    assert take(dataclasses.replace(dana, server=second_server))["locked"] is True


# When a lock ends


def test_after_the_holders_session_end_hook_another_session_takes_the_lock(dana: Session, cole: Session) -> None:
    dana.start()
    take(dana)
    while_held = refused(cole)

    dana.end()

    assert "Dana Dev" in while_held
    assert take(cole)["locked"] is True


def test_after_the_idle_time_without_a_call_from_the_holder_another_session_takes_the_lock(
    team: Team, dana: Session, cole: Session
) -> None:
    take(dana)

    team.server.clock.advance(minutes=29, seconds=59)
    just_before = refused(cole)
    team.server.clock.advance(seconds=1)

    assert "Dana Dev" in just_before
    assert take(cole)["locked"] is True


def test_any_call_from_the_holders_session_keeps_its_locks(team: Team, dana: Session, cole: Session) -> None:
    take(dana)

    team.server.clock.advance(minutes=29)
    dana.prompt("write a haiku about cats")
    team.server.clock.advance(minutes=29)

    assert "Dana Dev" in refused(cole)


def test_a_session_back_from_idle_gets_no_lock_back(team: Team, dana: Session, cole: Session) -> None:
    take(dana)
    team.server.clock.advance(minutes=31)

    dana.prompt("write a haiku about cats")
    for_cole = take(cole)

    assert for_cole["locked"] is True, "Dana's session is active again, but its lock ended while it was idle"
    assert "Cole Coder" in refused(dana)


# Files that never lock


@pytest.mark.parametrize(
    "path",
    [
        "package-lock.json",
        "web/yarn.lock",
        "uv.lock",
        "services/api/go.sum",
        "static/app.min.js",
        "static/app.js.map",
        "src/api/schema.generated.ts",
        "dist/assets/app.js",
        "build/lib/app.py",
    ],
)
def test_a_lockfile_or_generated_file_never_locks_and_the_answer_says_so(
    dana: Session, cole: Session, path: str
) -> None:
    for_dana = take(dana, path)
    for_cole = take(cole, path)

    for answer in (for_dana, for_cole):
        assert answer["locked"] is False
        assert answer["never_locks"] in NEVER_LOCK
        assert "never locks" in answer["message"]
        assert path in answer["message"]


def test_a_file_that_only_resembles_a_never_lock_pattern_locks(dana: Session) -> None:
    for path in ("src/distribution.py", "src/build/steps.py", "docs/yarn.lock.md", "src/sourcemap.py"):
        assert take(dana, path)["locked"] is True, path


# Paths and repositories


def test_a_path_is_kept_from_the_repositorys_root_with_forward_slashes(dana: Session, cole: Session) -> None:
    taken = take(dana, "src\\webhooks\\retry.py")

    assert taken["path"] == FILE
    for same_file in ("./src/webhooks/retry.py", "src/webhooks/../webhooks/retry.py", "src//webhooks/retry.py"):
        assert f"billing-api:{FILE}" in refused(cole, same_file), same_file


@pytest.mark.parametrize(
    "path", ["../billing-web/src/app.py", "src/../../secrets.env", "/etc/passwd", "C:\\work\\app.py", "", "."]
)
def test_a_path_that_leaves_the_repository_is_refused(dana: Session, path: str) -> None:
    refusal = refused(dana, path)

    assert "from the repository's root" in refusal


def test_a_session_without_a_repository_that_passes_none_is_refused_and_told_to_pass_one(dana: Session) -> None:
    nowhere = dataclasses.replace(dana, repository=None)

    refusal = refused(nowhere)
    passing_one = take(nowhere, repository="billing-api")

    assert "pass" in refusal and "`repository`" in refusal
    assert (passing_one["locked"], passing_one["repository"]) == (True, "billing-api")


def test_a_repository_name_that_is_not_one_is_refused(dana: Session) -> None:
    assert "Repository name" in refused(dana, repository="not a repository!")


def test_a_session_outside_a_restricted_project_cannot_take_or_release_its_locks(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-locks", 2301)
    take(it.owner.in_project(it.billing, "billing-api"))
    shut_out = it.dana.in_project(it.billing, "billing-api")

    refusals = [refused(shut_out), shut_out.refusal("release_lock", path=FILE, session=shut_out.identifier)]

    assert all("is restricted" in refusal for refusal in refusals)
    assert not any("E1001" in refusal or FILE in refusal for refusal in refusals), "nothing about who holds what"


# Releasing a lock


def test_the_holder_releases_a_file_and_another_session_locks_it_at_once(dana: Session, cole: Session) -> None:
    take(dana)
    while_held = refused(cole)

    released = release(dana)

    assert "Dana Dev" in while_held
    assert (released["released"], released["repository"], released["path"]) == (True, "billing-api", FILE)
    assert take(cole)["locked"] is True
    assert "Cole Coder" in refused(dana)


def test_a_session_that_does_not_hold_the_file_is_refused_with_the_reason(dana: Session, cole: Session) -> None:
    take(dana)

    anothers = cole.refusal("release_lock", path=FILE, session=cole.identifier)
    nobodys = cole.refusal("release_lock", path="src/unlocked.py", session=cole.identifier)

    assert "Dana Dev (emp-2)" in anothers
    assert "takeover" in anothers
    assert "holds no lock" in nobodys
    assert "Dana Dev" in refused(cole), "the refused release left Dana's lock where it was"


def test_the_guidance_for_taking_a_lock_says_to_release_the_file_when_the_work_on_it_is_finished(
    dana: Session,
) -> None:
    _, tools = dana.on_connecting()

    assert "release_lock" in tools["take_lock"]
    assert "finished" in tools["take_lock"]
    assert "take_lock" in tools["release_lock"]


# What the tickets that build on locks stand on


def test_a_projects_locks_and_who_holds_a_file_count_only_active_holders(
    team: Team, project: str, dana: Session, cole: Session
) -> None:
    """Asks the worker's locks module, read and never patched: it is the interface the hook and the console stand on,
    and the console's own server answers over HTTP in tests/test_console_sessions.py, not this module's server."""
    locks: Locks = team.server.app.state.locks
    take(dana.as_agent("claude-code"))
    team.server.clock.advance(minutes=20)
    take(cole, "src/invoices.py", repository="billing-web")

    both = locks.held(project)
    mine = locks.of(project, "billing-api", FILE)
    team.server.clock.advance(minutes=10)
    later = locks.held(project)

    assert [(lock.holder.member_id, lock.repository, lock.path) for lock in both] == [
        ("emp-2", "billing-api", FILE),
        ("emp-3", "billing-web", "src/invoices.py"),
    ]
    assert mine is not None
    assert (mine.holder.member_name, mine.holder.agent, mine.holder.identifier) == (
        "Dana Dev", "Claude Code", "test-session"
    )  # fmt: skip
    assert (both[1].taken_at - mine.taken_at).total_seconds() == 1200
    assert mine.last_used_at == mine.taken_at
    assert mine.activity is None, "a session's activity is another module's to supply"
    assert [lock.holder.member_id for lock in later] == ["emp-3"], "Dana's session went idle"
    assert locks.of(project, "billing-api", FILE) is None
    assert locks.never_locks(project, "web/yarn.lock") == "yarn.lock"
    assert locks.never_locks(project, FILE) is None
