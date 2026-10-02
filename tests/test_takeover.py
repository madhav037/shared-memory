"""Takeover: a member blocked by a lock has it moved to their own session, and the old holder is told once."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.support import Session, Team, ToolRefused, added_context, member
from tests.test_locks import FILE, refused, release, take

OTHER_FILE = "src/invoices.py"
HAIKU = "write a haiku about cats"


@pytest.fixture
def erin(team: Team, project: str) -> Session:
    return member(team, project, "emp-4", "Erin Eng")


def take_over(session: Session, path: str = FILE, **more: Any) -> dict[str, Any]:
    return take(session, path, takeover=True, **more)


def told(session: Session) -> str:
    """What the session's next prompt adds to its context."""
    return added_context(session.prompt(HAIKU))


# The lock moves


def test_a_takeover_of_a_file_another_session_holds_makes_the_caller_its_holder(dana: Session, cole: Session) -> None:
    take(dana)
    while_held = refused(cole)

    taken_over = take_over(cole)

    assert "Dana Dev" in while_held
    assert (taken_over["locked"], taken_over["repository"], taken_over["path"]) == (True, "billing-api", FILE)
    assert take(cole)["locked"] is True, "the lock is Cole's to keep"


def test_the_old_holders_next_take_of_the_file_is_refused_with_the_new_holders_details(
    team: Team, dana: Session, cole: Session
) -> None:
    take(dana)
    take_over(cole.as_agent("claude-code"))
    team.server.clock.advance(minutes=3)

    refusal = refused(dana)

    assert "Cole Coder (emp-3)" in refusal
    assert "Claude Code" in refusal
    assert f"billing-api:{FILE}" in refusal
    assert "3 minutes ago" in refusal


def test_a_takeover_moves_the_lock_of_the_same_members_other_session_too(dana: Session) -> None:
    second = dana.as_session("second-session")
    take(dana)

    take_over(second)

    assert "Dana Dev" in refused(dana)
    assert FILE in told(dana)
    assert FILE not in told(second)


# The old holder is told, once


def test_the_old_holders_next_prompt_names_the_file_and_the_member_and_the_one_after_does_not(
    dana: Session, cole: Session
) -> None:
    take(dana)
    take_over(cole)

    first = told(dana)
    second = told(dana)

    assert f"billing-api:{FILE}" in first
    assert "Cole Coder (emp-3)" in first
    assert "takeover" in first
    assert FILE not in second
    assert "Cole Coder" not in second


def test_the_notice_reaches_the_session_that_held_the_lock_not_the_members_other_session(
    dana: Session, cole: Session
) -> None:
    other = dana.as_session("second-session")
    other.start()
    take(dana)
    take_over(cole)

    for_the_other = told(other)
    for_the_old_holder = told(dana)

    assert FILE not in for_the_other
    assert "Cole Coder" not in for_the_other
    assert FILE in for_the_old_holder
    assert FILE not in told(cole), "the session that took the file over is told nothing"


def test_an_old_holder_with_no_prompt_hook_is_told_in_the_result_of_its_next_take_lock(
    dana: Session, cole: Session
) -> None:
    before = take(dana)
    take_over(cole)

    next_take = take(dana, OTHER_FILE)
    one_after = take(dana, OTHER_FILE)

    assert before["notices"] == []
    assert next_take["locked"] is True
    assert len(next_take["notices"]) == 1
    assert f"billing-api:{FILE}" in next_take["notices"][0]
    assert "Cole Coder (emp-3)" in next_take["notices"][0]
    assert one_after["notices"] == []
    assert FILE not in told(dana), "told once, wherever it was told"


def test_an_old_holder_with_no_prompt_hook_is_told_in_the_result_of_its_next_set_activity(
    dana: Session, cole: Session
) -> None:
    take(dana)
    take_over(cole)

    stated = dana.call("set_activity", activity="Retrying webhooks", session=dana.identifier)
    again = dana.call("set_activity", activity="Retrying webhooks in billing-api", session=dana.identifier)

    assert len(stated["notices"]) == 1
    assert f"billing-api:{FILE}" in stated["notices"][0]
    assert "Cole Coder (emp-3)" in stated["notices"][0]
    assert again["notices"] == []


def test_the_old_holder_is_told_the_activity_of_the_session_that_took_the_file_over(
    dana: Session, cole: Session
) -> None:
    take(dana)
    cole.call("set_activity", activity="Adding retries to the webhook sender", session=cole.identifier)

    take_over(cole)

    assert "Their activity: Adding retries to the webhook sender" in told(dana)
    assert "Their activity: Adding retries to the webhook sender" in refused(dana)


def test_a_refused_take_leaves_the_notice_waiting_for_the_old_holder(dana: Session, cole: Session) -> None:
    take(dana)
    take_over(cole)

    refused(dana)

    assert FILE in told(dana)


def test_a_session_that_ends_is_not_told_of_the_takeover_when_it_starts_again(dana: Session, cole: Session) -> None:
    dana.start()
    take(dana)
    take_over(cole)

    dana.end()
    dana.start()

    assert FILE not in told(dana)


# Nothing to take over


def test_a_takeover_of_a_free_file_just_takes_the_lock_and_tells_nobody(dana: Session, cole: Session) -> None:
    dana.start()

    taken = take_over(cole)

    assert taken["locked"] is True
    assert taken["notices"] == []
    assert "Cole Coder" in refused(dana)
    assert FILE not in told(dana)
    assert FILE not in told(cole)


def test_a_takeover_of_a_file_the_session_already_holds_keeps_the_lock_and_tells_nobody(
    team: Team, dana: Session, cole: Session
) -> None:
    first = take(dana)
    team.server.clock.advance(minutes=5)

    kept = take_over(dana)

    assert kept["locked"] is True
    assert kept["taken_at"] == first["taken_at"]
    assert kept["notices"] == []
    assert FILE not in told(dana)
    assert "Dana Dev" in refused(cole)


def test_a_takeover_of_a_file_whose_holder_went_idle_tells_nobody(team: Team, dana: Session, cole: Session) -> None:
    take(dana)
    team.server.clock.advance(minutes=31)

    taken = take_over(cole)

    assert taken["locked"] is True
    assert FILE not in told(dana), "its lock ended by going idle, which it is told instead"


def test_a_takeover_of_a_file_that_never_locks_takes_nothing(dana: Session) -> None:
    answer = take_over(dana, "web/yarn.lock")

    assert answer["locked"] is False
    assert answer["never_locks"] == "yarn.lock"


# The member decides


def test_a_refused_take_says_the_member_can_ask_for_a_takeover(dana: Session, cole: Session) -> None:
    take(dana)

    refusal = refused(cole)

    assert "takeover" in refusal
    assert "`takeover`" in refusal
    assert "member" in refusal


def test_the_guidance_for_taking_a_lock_says_to_pass_takeover_only_once_the_member_has_said_so(dana: Session) -> None:
    _, tools = dana.on_connecting()

    assert "takeover" in tools["take_lock"]
    assert "only once your member has said so" in tools["take_lock"]


# Decided by Postgres, across workers


def test_a_takeover_racing_the_holders_release_leaves_the_caller_holding_the_file(
    dana: Session, cole: Session, elsewhere: Callable[[Session], Session]
) -> None:
    for attempt in range(5):
        path = f"src/webhooks/attempt_{attempt}.py"
        take(dana, path)

        releasing = dana.call_soon("release_lock", path=path, session=dana.identifier)
        taking_over = elsewhere(cole).call_soon("take_lock", path=path, session=cole.identifier, takeover=True)

        assert taking_over.result(timeout=30)["locked"] is True
        try:
            releasing.result(timeout=30)
            released = True
        except ToolRefused as refusal:
            released = False
            assert "Cole Coder (emp-3)" in str(refusal)
        assert "Cole Coder" in refused(dana, path)
        assert (path in told(dana)) is not released, "told of a takeover only when there was a lock to take over"
        with pytest.raises(ToolRefused):
            release(dana, path)


def test_two_takeovers_racing_each_other_leave_one_holder_and_tell_each_session_that_lost_the_file(
    dana: Session, cole: Session, erin: Session, elsewhere: Callable[[Session], Session]
) -> None:
    for attempt in range(5):
        path = f"src/webhooks/attempt_{attempt}.py"
        take(dana, path)
        arguments = {"path": path, "session": "test-session", "takeover": True}
        racing = {
            "Cole Coder": (cole, cole.call_soon("take_lock", **arguments)),
            "Erin Eng": (erin, elsewhere(erin).call_soon("take_lock", **arguments)),
        }

        answers = {name: future.result(timeout=30) for name, (_, future) in racing.items()}
        assert all(answer["locked"] is True for answer in answers.values())

        refusal = refused(dana, path)
        holders = [name for name in racing if name in refusal]
        assert len(holders) == 1
        (holder,) = holders
        (lost,) = [name for name in racing if name != holder]
        for_dana = told(dana)
        # The session that lost the file is told with its own answer when the other takeover landed before that
        # answer was written, and on its next prompt otherwise: once, either way.
        for_the_loser = "\n".join([*answers[lost]["notices"], told(racing[lost][0])])
        assert for_dana.count(path) == 1, "Dana's lock was taken over once"
        assert lost in for_dana, "by whoever got there first"
        assert for_the_loser.count(path) == 1
        assert holder in for_the_loser
        assert answers[holder]["notices"] == []
        assert path not in told(racing[holder][0])
