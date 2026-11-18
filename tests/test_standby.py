"""Standby (ADR-0027, #524): a session awaiting an answer stands by through `/hooks/standby`, which the server holds
until there is news for the session, the same news `waiting_for` gathers for every hook, and answers with it, told
once. Otherwise it ends with "nothing yet" at its cap, "replaced" when a newer standby of the session starts, or
"moved on" at the session's next prompt.

Each standby here is held on a thread of its own over real HTTP, as a coding agent's background command holds it, while
the test drives the other sessions and moves the server's clock. The server checks every 50 milliseconds rather than
every 2 seconds. The collisions are made as `test_gates.py` makes them, with this module's own server for the chosen
embeddings."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from typing import Any

import httpx
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import REPO_ROOT, RunningServer, Session, Team, TestClock, added_context, fresh_database
from tests.test_collisions import RETRIES, WEBHOOKS, ChosenSimilarity, state
from tests.test_gates import URGENT, answer_gate, collide, heard, send_urgent
from tests.test_locks import take
from tests.test_messages import ASKED, PROMPT, REPLIED, send
from tests.test_mute import mute

CHECK_SECONDS = 0.05
# Long enough for a standby that should still be held to have been checked many times over.
STILL_HELD_SECONDS = 0.4
ANSWERED_WITHIN_SECONDS = 15


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    """This module's own server, in place of the one every other module shares, for the chosen embeddings and a
    short check interval."""
    settings = Settings(
        database_url=fresh_database("shared_memory_standby"),
        memory_root=tmp_path_factory.mktemp("standby-memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
        rate_limit_on=False,
        standby_check_seconds=CHECK_SECONDS,
    )
    clock = TestClock()
    embedder = ChosenSimilarity(settings.model_cache)
    with start_blocking_portal() as portal:
        running = RunningServer(build_app(settings, clock=clock, embedder=embedder), settings, clock, portal)
        try:
            yield running
        finally:
            running.stop()


@pytest.fixture(scope="module")
def second_server(server: RunningServer) -> Iterator[RunningServer]:
    """A second server instance on this module's database, with its clock: to Postgres, a second worker."""
    app = build_app(server.settings, clock=server.clock, embedder=ChosenSimilarity(server.settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, server.settings, server.clock, portal)
        try:
            yield running
        finally:
            running.stop()


@pytest.fixture(params=["one worker", "two workers"])
def elsewhere(request: pytest.FixtureRequest) -> Callable[[Session], Session]:
    """Where the answer is recorded: on the server holding the standby, or on a second worker."""
    if request.param == "one worker":
        return lambda session: session
    other: RunningServer = request.getfixturevalue("second_server")
    return lambda session: dataclasses.replace(session, server=other)


def standing_by(session: Session) -> Future[httpx.Response]:
    """Start a standby for the session, held on a thread of its own, and return once the server holds it."""
    held = session.stand_by()
    deadline = time.monotonic() + ANSWERED_WITHIN_SECONDS
    while session.identifier not in session.on_standby():
        if held.done():
            raise AssertionError(f"the standby ended at once: {held.result().text}")
        if time.monotonic() > deadline:
            raise AssertionError("the standby was never held")
        time.sleep(CHECK_SECONDS / 2)
    return held


def answer_of(held: Future[httpx.Response]) -> dict[str, Any]:
    """How a held standby ended, once it has."""
    response = held.result(timeout=ANSWERED_WITHIN_SECONDS)
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def news_in(held: Future[httpx.Response]) -> str:
    answer = answer_of(held)
    assert answer["ended"] == "news", answer
    news: list[str] = answer["news"]
    return "\n\n".join(news)


def still_held(held: Future[httpx.Response]) -> bool:
    time.sleep(STILL_HELD_SECONDS)
    return not held.done()


def end(session: Session, held: Future[httpx.Response]) -> dict[str, Any]:
    """End a standby a test leaves held, by the session's next prompt."""
    session.prompt(PROMPT)
    return answer_of(held)


# The answer the session awaits


def test_a_standby_ends_with_the_answer_when_the_earlier_member_agrees(
    owner: Session, dana: Session, elsewhere: Callable[[Session], Session]
) -> None:
    collide(owner, dana)
    held = standing_by(dana)

    answer_gate(elsewhere(owner), "emp-2", "agree", "Go ahead, I'm on the docs.")

    news = news_in(held)
    assert "[gate]" in news and "Olive Owner" in news and "agreed" in news
    assert "Go ahead, I'm on the docs." in news


def test_a_standby_ends_with_the_answer_when_the_earlier_member_refuses(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    held = standing_by(dana)

    answer_gate(owner, "emp-2", "refuse")

    news = news_in(held)
    assert "Olive Owner" in news and "refused" in news


def test_a_standby_ends_with_the_reply_when_the_earlier_member_replies(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")
    held = standing_by(dana)

    send(owner, "emp-2", REPLIED)

    news = news_in(held)
    assert "[message]" in news and REPLIED in news and "Olive Owner" in news


def test_a_standby_ends_with_the_gate_lifting_at_the_projects_wait(
    team: Team, owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=2)
    held = standing_by(dana)
    team.server.clock.advance(minutes=2, seconds=59)
    assert still_held(held), "the wait has a second to run"

    team.server.clock.advance(seconds=1)

    news = news_in(held)
    assert "[gate]" in news and "Olive Owner" in news and "wait" in news


# Other news


def test_a_standby_ends_with_a_collision(owner: Session, dana: Session) -> None:
    state(dana, RETRIES)
    held = standing_by(dana)

    state(owner, WEBHOOKS)

    news = news_in(held)
    assert "[possible collision]" in news and "Olive Owner" in news


def test_a_standby_ends_with_a_lock_taken_over(owner: Session, dana: Session) -> None:
    dana.start()
    take(dana)
    held = standing_by(dana)

    take(owner, takeover=True)

    news = news_in(held)
    assert "Olive Owner" in news and "takeover" in news


def test_a_standby_ends_with_a_message(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    held = standing_by(dana)

    send(owner, "emp-2", ASKED)

    news = news_in(held)
    assert ASKED in news and "Olive Owner" in news


def test_a_muted_sessions_standby_ends_only_on_what_mute_lets_through(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    mute(dana)
    held = standing_by(dana)

    send(owner, "emp-2", ASKED)
    assert still_held(held), "a message that is not urgent waits for the next prompt"
    answer_gate(owner, "emp-2", "agree")

    news = news_in(held)
    assert "agreed" in news
    assert ASKED not in news
    assert ASKED in added_context(dana.prompt(PROMPT)), "the next prompt delivers it"


def test_a_muted_sessions_standby_ends_on_an_urgent_message(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    mute(owner)
    heard(owner)
    held = standing_by(owner)

    send_urgent(dana, "owner-1")

    assert URGENT in news_in(held)


# Told once


def test_news_handed_over_by_a_standby_is_not_told_again_by_the_next_hook(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    held = standing_by(dana)
    answer_gate(owner, "emp-2", "agree")
    assert "agreed" in news_in(held)

    assert "agreed" not in heard(dana), "not on the next tool call"
    assert "agreed" not in added_context(dana.prompt(PROMPT)), "nor on the next prompt"


# Ending without news


def test_a_standby_answers_nothing_yet_at_its_cap_with_the_time_left_of_the_projects_wait(
    team: Team, owner: Session
) -> None:
    owner.call("project_wait", minutes=12)
    owner.start()
    held = standing_by(owner)
    team.server.clock.advance(minutes=4, seconds=59)
    assert still_held(held), "a second short of its cap"

    team.server.clock.advance(seconds=1)

    answer = answer_of(held)
    assert answer["ended"] == "nothing_yet"
    assert answer["news"] == []
    assert answer["wait_left_seconds"] == 7 * 60
    assert "nothing yet" in answer["message"].lower() and "7 minutes" in answer["message"]


def test_a_standby_is_held_no_longer_than_the_projects_wait(team: Team, owner: Session) -> None:
    owner.call("project_wait", minutes=2)
    owner.start()
    held = standing_by(owner)

    team.server.clock.advance(minutes=2)

    answer = answer_of(held)
    assert answer["ended"] == "nothing_yet"
    assert answer["wait_left_seconds"] == 0


def test_a_standby_answers_replaced_when_a_newer_one_starts(dana: Session) -> None:
    dana.start()
    first = standing_by(dana)

    second = dana.stand_by()

    answer = answer_of(first)
    assert answer["ended"] == "replaced"
    assert "newer standby" in answer["message"]
    assert end(dana, second)["ended"] == "moved_on"


def test_a_standby_answers_moved_on_when_the_next_prompt_arrives(dana: Session) -> None:
    dana.start()
    held = standing_by(dana)

    dana.prompt(PROMPT)

    answer = answer_of(held)
    assert answer["ended"] == "moved_on"
    assert "moved on" in answer["message"]


def test_the_next_prompt_delivers_the_news_itself_as_it_always_has(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()
    held = standing_by(dana)

    told = added_context(dana.prompt(PROMPT))
    send(owner, "emp-2", ASKED)

    assert answer_of(held)["ended"] == "moved_on"
    assert ASKED not in told
    assert ASKED in heard(dana), "the standby that ended took nothing with it"


# The request


def test_a_request_without_the_sessions_token_is_refused(server: RunningServer, dana: Session) -> None:
    dana.start()
    assert dana.token is not None
    without = {key: value for key, value in dana.headers().items() if key != "Authorization"}

    refused = httpx.post(f"{server.url}/hooks/standby", json={"session_id": dana.identifier}, headers=without)
    on_the_command_line = httpx.post(
        f"{server.url}/hooks/standby",
        json={"session_id": dana.identifier},
        params={"token": dana.token},
        headers=without,
    )

    assert refused.status_code == 401
    assert on_the_command_line.status_code == 401, "a personal token is read only from the Authorization header"
    assert dana.identifier not in dana.on_standby()


def test_a_request_naming_no_session_is_refused(server: RunningServer, dana: Session) -> None:
    refused = httpx.post(f"{server.url}/hooks/standby", json={}, headers=dana.headers())

    assert refused.status_code == 400
    assert "session" in refused.json()["message"]


def test_a_second_held_standby_for_a_session_replaces_the_first(dana: Session) -> None:
    dana.start()
    first = standing_by(dana)
    second = dana.stand_by()
    assert answer_of(first)["ended"] == "replaced"

    assert dana.on_standby().count(dana.identifier) == 1, "never more than one held"
    assert still_held(second)
    end(dana, second)


def test_each_session_of_a_member_has_its_own_standby(dana: Session) -> None:
    other = dana.as_session("other-session")
    dana.start()
    other.start()
    first = standing_by(dana)

    second = standing_by(other)

    assert still_held(first), "another session's standby replaces nothing"
    end(dana, first)
    end(other, second)


# Settings


def test_the_standby_settings_default_to_five_minutes_and_two_seconds() -> None:
    settings = Settings.from_env({})

    assert settings.standby_cap_minutes == 5
    assert settings.standby_check_seconds == 2


def test_the_standby_settings_read_their_environment_variables() -> None:
    settings = Settings.from_env(
        {"SHARED_MEMORY_STANDBY_CAP_MINUTES": "3", "SHARED_MEMORY_STANDBY_CHECK_SECONDS": "0.5"}
    )

    assert settings.standby_cap_minutes == 3
    assert settings.standby_check_seconds == 0.5
