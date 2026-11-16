"""Mute (#514): a muted session's messages that are not urgent wait for its next prompt or its unmute, while urgent
messages and gate answers still reach it on a tool call. A sender, and a later session gated on a muted session's
work, are told it is muted, and the gate's wait runs the same.

The collisions here are made as `test_gates.py` makes them, with this module's own server for the chosen embeddings."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import REPO_ROOT, RunningServer, Session, Team, TestClock, added_context, fresh_database
from tests.test_before_edit import ALLOWED, reason_in
from tests.test_collisions import ChosenSimilarity
from tests.test_gates import GATED, URGENT, answer_gate, collide, heard, send_urgent
from tests.test_locks import FILE
from tests.test_messages import ASKED, PROMPT, send


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    """This module's own server, in place of the one every other module shares, for the chosen embeddings."""
    settings = Settings(
        database_url=fresh_database("shared_memory_mute"),
        memory_root=tmp_path_factory.mktemp("mute-memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
        rate_limit_on=False,
    )
    clock = TestClock()
    embedder = ChosenSimilarity(settings.model_cache)
    with start_blocking_portal() as portal:
        running = RunningServer(build_app(settings, clock=clock, embedder=embedder), settings, clock, portal)
        try:
            yield running
        finally:
            running.stop()


def mute(session: Session, on: bool = True) -> dict[str, Any]:
    muted: dict[str, Any] = session.call("mute", session=session.identifier, on=on)
    return muted


def heard_on_prompt(session: Session) -> str:
    return added_context(session.prompt(PROMPT))


# Held back


def test_a_muted_session_hears_a_message_not_on_a_tool_call_but_on_its_next_prompt(
    owner: Session, dana: Session
) -> None:
    owner.start()
    dana.start()
    assert mute(dana)["muted"] is True

    send(owner, "emp-2", ASKED)

    assert ASKED not in heard(dana), "held back on a tool call"
    assert ASKED in heard_on_prompt(dana), "the next prompt delivers it"
    assert ASKED not in heard(dana), "delivered once"


def test_a_prompt_delivers_but_leaves_the_session_muted(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    mute(dana)
    heard_on_prompt(dana)

    send(owner, "emp-2", ASKED)

    assert ASKED not in heard(dana)


def test_unmute_delivers_what_was_held_back(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    mute(dana)
    send(owner, "emp-2", ASKED)
    assert ASKED not in heard(dana)

    unmuted = mute(dana, on=False)

    assert unmuted["muted"] is False
    assert any(ASKED in notice for notice in unmuted["notices"]), "unmuting delivers the rest"
    assert ASKED not in heard(dana), "delivered once"


def test_a_session_that_is_not_muted_hears_a_message_on_its_tool_call(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    mute(dana)
    mute(dana, on=False)

    send(owner, "emp-2", ASKED)

    assert ASKED in heard(dana)


def test_mute_holds_back_only_its_own_session(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    other = dana.as_session("dana-second")
    other.start()
    mute(dana)

    send(owner, "emp-2", ASKED)

    assert ASKED in heard(other)


# Gets through


def test_an_urgent_message_gets_through_a_mute(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    mute(owner)

    send_urgent(dana, "owner-1")

    assert URGENT in heard(owner)


def test_a_gate_answer_gets_through_a_mute(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    mute(dana)

    answer_gate(owner, "emp-2", "agree", "Go ahead, I am only on the docs.")
    told = heard(dana)

    assert "agreed" in told and "Go ahead, I am only on the docs." in told


def test_a_muted_earlier_session_is_still_told_a_gate_waits_on_its_work(owner: Session, dana: Session) -> None:
    owner.start()
    mute(owner)
    collide(owner, dana)

    assert "[gate]" in heard(owner)


# Told it is muted


def test_the_sender_is_told_the_recipient_is_muted(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    assert send(owner, "emp-2", ASKED)["muted"] is False

    mute(dana)

    assert send(owner, "emp-2", ASKED)["muted"] is True


def test_a_member_with_one_session_not_muted_is_not_muted(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    dana.as_session("dana-second").start()
    mute(dana)

    assert send(owner, "emp-2", ASKED)["muted"] is False


def test_a_gated_later_session_is_told_the_earlier_session_is_muted_and_the_wait_still_runs(
    team: Team, owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    assert "muted" not in reason_in(dana.edit(FILE))

    mute(owner)
    reason = reason_in(dana.edit(FILE))

    assert reason.startswith(GATED)
    assert "Olive Owner (owner-1)" in reason and "muted" in reason
    assert "5 minutes left" in reason, "the wait runs the same"

    team.server.clock.advance(minutes=5)

    assert dana.edit(FILE) == ALLOWED, "the wait lifts it while muted"
