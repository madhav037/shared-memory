"""Standby (ADR-0027, #524): a session awaiting an answer stands by through `/hooks/standby`, which the server holds
until there is news for the session, the same news `waiting_for` gathers for every hook, and answers with it, told
once. Otherwise it ends with "nothing yet" at its cap, "replaced" when a newer standby of the session starts, or
"moved on" at the session's next prompt. The `stand_by` tool (#525) holds the same standby inside an MCP tool call,
for a coding agent that can't be woken by a background command, and answers the same way.

Each standby here is held on a thread of its own over real HTTP, as a coding agent's background command holds it, while
the test drives the other sessions and moves the server's clock. The server checks every 50 milliseconds rather than
every 2 seconds, and holds a `stand_by` call at most `TOOL_CAP_SECONDS`. The collisions are made as `test_gates.py` makes them, with this module's own server for the chosen
embeddings."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import httpx
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import STAND_BY_TOOL_CAP_SECONDS, Settings
from shared_memory.connection import connection_kit
from shared_memory.standby import STAND_BY_SECONDS
from tests.support import REPO_ROOT, RunningServer, Session, Team, TestClock, added_context, fresh_database
from tests.test_collisions import RETRIES, WEBHOOKS, ChosenSimilarity, state
from tests.test_connection_kit import (
    POWERSHELLS,
    background_standby_commands,
    claude_code_session_start_hook,
    claude_code_skill,
    standby_command,
    without_plugin_settings,
    without_the_token,
)
from tests.test_before_edit import reason_in
from tests.test_gates import GATED, SHOW_FIRST, URGENT, answer_gate, collide, heard, send_urgent, warning_in
from tests.test_locks import FILE, take
from tests.test_messages import ASKED, PROMPT, REPLIED, send
from tests.test_mute import mute

CHECK_SECONDS = 0.05
# Long enough for a standby that should still be held to have been checked many times over.
STILL_HELD_SECONDS = 0.4
ANSWERED_WITHIN_SECONDS = 15
# This module's server's cap on one `stand_by` call, below the default so that the cap is what ends it.
TOOL_CAP_SECONDS = 60


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
        standby_tool_cap_seconds=TOOL_CAP_SECONDS,
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
    return held_by(session, session.stand_by())


def standing_by_the_tool(session: Session, **arguments: Any) -> Future[Any]:
    """Call `stand_by` for the session, the call held while the test goes on, and return once the server holds it."""
    return held_by(session, session.call_soon("stand_by", session=session.identifier, **arguments))


def held_by(session: Session, held: Future[Any]) -> Future[Any]:
    deadline = time.monotonic() + ANSWERED_WITHIN_SECONDS
    while session.identifier not in session.on_standby():
        if held.done():
            raise AssertionError(f"the standby ended at once: {held.result()}")
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


def tool_answer_of(held: Future[Any]) -> dict[str, Any]:
    """How a held `stand_by` call ended, once it has."""
    answer: dict[str, Any] = held.result(timeout=ANSWERED_WITHIN_SECONDS)
    return answer


def still_held(held: Future[Any]) -> bool:
    time.sleep(STILL_HELD_SECONDS)
    return not held.done()


def end(session: Session, held: Future[httpx.Response]) -> dict[str, Any]:
    """End a standby a test leaves held, by the session's next prompt."""
    session.prompt(PROMPT)
    return answer_of(held)


def end_tool(session: Session, held: Future[Any]) -> dict[str, Any]:
    """End a `stand_by` call a test leaves held, by the session's next prompt."""
    session.prompt(PROMPT)
    return tool_answer_of(held)


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


def test_a_standby_ends_with_the_gate_lifting_when_the_earlier_session_ends(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    held = standing_by(dana)

    owner.end()

    news = news_in(held)
    assert "[gate]" in news and "Olive Owner" in news and "ended or went idle" in news
    assert "Olive Owner" not in heard(dana), "told once"


def test_a_standby_ends_with_the_gate_lifting_when_the_earlier_session_goes_idle(
    team: Team, owner: Session, dana: Session
) -> None:
    owner.call("project_wait", minutes=60)
    collide(owner, dana)
    team.server.clock.advance(minutes=27)
    assert GATED in reason_in(dana.edit(FILE)), "Dana's session stays active"
    held = standing_by(dana)

    team.server.clock.advance(minutes=4)

    news = news_in(held)
    assert "[gate]" in news and "Olive Owner" in news and "ended or went idle" in news


def test_a_gate_lifted_by_an_answer_is_not_told_again_when_the_earlier_session_ends(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "agree")
    assert "agreed" in heard(dana)

    owner.end()

    assert "ended or went idle" not in heard(dana)


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


# What the member is shown (#590)


def said_in(box: str) -> str:
    """What a warning's box says, its lines joined, frame left out."""
    return " ".join(line.strip("│ ") for line in box.splitlines()[1:-1] if line.strip("│ "))


def assert_shows_the_gate_warning_first(answer: dict[str, Any]) -> None:
    """The earlier session hears a gate start: `member` holds its warning, `message` shows it first."""
    assert answer["ended"] == "news"
    member = answer["member"]
    assert member.startswith("**⚠ Dana Dev is waiting on you**")
    heading, box = warning_in(member)
    assert heading == "⚠ Dana Dev is waiting on you"
    assert "5 min left" in said_in(box) and "agree · refuse" in said_in(box)
    assert answer["message"].startswith(f"{SHOW_FIRST}\n\n{member}\n\n")
    assert "answer_gate" in answer["message"].removeprefix(f"{SHOW_FIRST}\n\n{member}"), "the agent's lines follow"
    assert SHOW_FIRST not in answer["message"].removeprefix(SHOW_FIRST), "the instruction is given once"
    assert any(each.startswith(SHOW_FIRST) and "[gate] Dana Dev (emp-2)" in each for each in answer["news"])


def test_standby_hook_news_with_a_warning_answers_member_and_shows_it_first(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    assert_shows_the_gate_warning_first(answer_of(owner.stand_by()))


def test_stand_by_tool_news_with_a_warning_answers_member_and_shows_it_first(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    assert_shows_the_gate_warning_first(owner.call("stand_by", session=owner.identifier, seconds=20))


def test_standby_hook_news_without_a_warning_answers_member_null_and_the_news_as_before(
    owner: Session, dana: Session
) -> None:
    state(dana, RETRIES)
    held = standing_by(dana)

    state(owner, WEBHOOKS)

    answer = answer_of(held)
    assert answer["ended"] == "news"
    assert "member" in answer and answer["member"] is None
    assert answer["message"] == "\n\n".join(answer["news"])
    assert not answer["message"].startswith(SHOW_FIRST)


def test_standby_hook_nothing_yet_answers_member_with_the_hourglass_warning_and_the_time_left(
    team: Team, owner: Session
) -> None:
    owner.call("project_wait", minutes=12)
    owner.start()
    held = standing_by(owner)

    team.server.clock.advance(minutes=5)

    answer = answer_of(held)
    assert answer["ended"] == "nothing_yet"
    heading, box = warning_in(answer["member"])
    assert heading.startswith("⏳ ")
    assert "7 min left" in said_in(box) and "stand by once more" in said_in(box)
    assert "UTC" not in answer["member"]
    assert answer["message"].startswith(f"{SHOW_FIRST}\n\n{answer['member']}\n\n[standby] Nothing yet")
    assert "7 minutes" in answer["message"]


def test_standby_hook_nothing_yet_after_the_projects_wait_says_the_wait_has_passed(team: Team, owner: Session) -> None:
    owner.call("project_wait", minutes=2)
    owner.start()
    held = standing_by(owner)

    team.server.clock.advance(minutes=2)

    answer = answer_of(held)
    assert answer["ended"] == "nothing_yet"
    heading, box = warning_in(answer["member"])
    assert heading.startswith("⏳ ")
    assert "wait has passed" in said_in(box) and "min left" not in said_in(box)
    assert answer["message"].startswith(SHOW_FIRST)


def test_stand_by_tool_nothing_yet_answers_member_with_the_hourglass_warning_and_the_time_left(
    team: Team, owner: Session
) -> None:
    owner.start()
    held = standing_by_the_tool(owner, seconds=20)

    team.server.clock.advance(seconds=20)

    answer = tool_answer_of(held)
    assert answer["ended"] == "nothing_yet"
    heading, box = warning_in(answer["member"])
    assert heading.startswith("⏳ ") and "5 min left" in said_in(box)
    assert answer["message"].startswith(f"{SHOW_FIRST}\n\n{answer['member']}")


def test_standby_answers_that_neither_hear_news_nor_nothing_yet_carry_no_member(dana: Session) -> None:
    dana.start()
    first = standing_by(dana)

    second = dana.stand_by()

    replaced = answer_of(first)
    assert replaced["ended"] == "replaced" and "member" not in replaced
    moved_on = end(dana, second)
    assert moved_on["ended"] == "moved_on" and "member" not in moved_on


def test_stand_by_tool_description_documents_the_member_field(dana: Session) -> None:
    _, described = dana.on_connecting()

    said = described["stand_by"]
    assert "member" in said and "word for word" in said


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


# The stand_by tool (#525)


def test_stand_by_ends_with_an_answer_given_meanwhile(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    held = standing_by_the_tool(dana)

    answer_gate(owner, "emp-2", "agree", "Go ahead, I'm on the docs.")

    answer = tool_answer_of(held)
    assert answer["ended"] == "news"
    news = "\n\n".join(answer["news"])
    assert "[gate]" in news and "Olive Owner" in news and "agreed" in news
    assert "Go ahead, I'm on the docs." in news
    assert answer["message"] == news


def test_stand_by_answers_nothing_yet_after_its_seconds(team: Team, owner: Session) -> None:
    owner.start()
    held = standing_by_the_tool(owner, seconds=20)
    team.server.clock.advance(seconds=19)
    assert still_held(held), "a second short of its seconds"

    team.server.clock.advance(seconds=1)

    answer = tool_answer_of(held)
    assert answer["ended"] == "nothing_yet"
    assert answer["news"] == []
    assert answer["wait_left_seconds"] == 5 * 60 - 20
    assert "nothing yet" in answer["message"].lower() and "5 minutes" in answer["message"]


def test_stand_by_seconds_above_the_servers_cap_are_held_only_to_the_cap(team: Team, owner: Session) -> None:
    owner.start()
    held = standing_by_the_tool(owner, seconds=600)
    team.server.clock.advance(seconds=TOOL_CAP_SECONDS - 1)
    assert still_held(held), "a second short of the cap"

    team.server.clock.advance(seconds=1)

    answer = tool_answer_of(held)
    assert answer["ended"] == "nothing_yet"
    assert answer["wait_left_seconds"] == 5 * 60 - TOOL_CAP_SECONDS


def test_stand_by_is_held_45_seconds_by_default(team: Team, owner: Session) -> None:
    owner.start()
    held = standing_by_the_tool(owner)
    team.server.clock.advance(seconds=44)
    assert still_held(held), "a second short of 45"

    team.server.clock.advance(seconds=1)

    answer = tool_answer_of(held)
    assert answer["ended"] == "nothing_yet"
    assert answer["wait_left_seconds"] == 5 * 60 - 45


def test_news_handed_over_by_stand_by_is_not_told_again_by_the_next_hook_or_tool_result(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    held = standing_by_the_tool(dana)
    answer_gate(owner, "emp-2", "agree")
    assert "agreed" in "\n\n".join(tool_answer_of(held)["news"])

    assert not any("agreed" in notice for notice in mute(dana, on=False)["notices"]), "not by a tool's result"
    assert "agreed" not in heard(dana), "nor on the next tool call"
    assert "agreed" not in added_context(dana.prompt(PROMPT)), "nor on the next prompt"


def test_a_standby_started_through_the_tool_is_replaced_by_one_through_the_endpoint(dana: Session) -> None:
    dana.start()
    through_the_tool = standing_by_the_tool(dana)

    through_the_endpoint = dana.stand_by()

    answer = tool_answer_of(through_the_tool)
    assert answer["ended"] == "replaced"
    assert "newer standby" in answer["message"]
    assert end(dana, through_the_endpoint)["ended"] == "moved_on"


def test_a_standby_started_through_the_endpoint_is_replaced_by_one_through_the_tool(dana: Session) -> None:
    dana.start()
    through_the_endpoint = standing_by(dana)

    through_the_tool = dana.call_soon("stand_by", session=dana.identifier)

    assert answer_of(through_the_endpoint)["ended"] == "replaced"
    assert dana.on_standby().count(dana.identifier) == 1, "never more than one held"
    assert end_tool(dana, through_the_tool)["ended"] == "moved_on"


def test_a_stand_by_call_whose_asker_went_away_holds_the_standby_no_longer(owner: Session) -> None:
    owner.start()
    held = standing_by_the_tool(owner)

    held.cancel()

    deadline = time.monotonic() + ANSWERED_WITHIN_SECONDS
    while owner.identifier in owner.on_standby():
        assert time.monotonic() < deadline, "the standby was held for an asker that had gone"
        time.sleep(CHECK_SECONDS / 2)


def test_stand_by_says_to_call_it_again_until_the_projects_wait_has_passed(dana: Session) -> None:
    _, described = dana.on_connecting()

    said = described["stand_by"]
    assert "again" in said and "wait" in said and "once more" in said

# Claude Code's background command (#526)


@pytest.mark.skipif(shutil.which("curl") is None, reason="Claude Code's standby command runs curl, which isn't installed")
def test_claude_codes_standby_command_run_in_a_posix_shell_hears_the_sessions_news(
    owner: Session, dana: Session, tmp_path: Path
) -> None:
    """The session starts through the plugin's session-start hook, which alone is given the plugin's settings; the
    agent's command, like every command of Claude Code's agent, runs after the environment file is read."""
    assert dana.token is not None and dana.project is not None and dana.repository is not None
    # What `.claude/settings.json` gives every command in the repository.
    repository = {**without_plugin_settings(), "SHARED_MEMORY_PROJECT": dana.project, "SHARED_MEMORY_REPOSITORY": dana.repository}
    env_file = tmp_path / "claude-env"
    started = subprocess.run(
        ["sh", "-c", claude_code_session_start_hook()],
        input=json.dumps({"session_id": dana.identifier, "hook_event_name": "SessionStart", "source": "startup"}),
        capture_output=True,
        text=True,
        timeout=ANSWERED_WITHIN_SECONDS,
        env={
            **repository,
            "CLAUDE_ENV_FILE": str(env_file),
            "CLAUDE_PLUGIN_OPTION_PERSONAL_TOKEN": dana.token,
            "CLAUDE_PLUGIN_OPTION_SERVER_URL": dana.server.url,
        },
    )
    assert started.returncode == 0 and "hookSpecificOutput" in json.loads(started.stdout), started
    collide(owner, dana)
    command = standby_command(claude_code_skill()).replace("<session>", dana.identifier)
    shell = subprocess.Popen(
        ["sh", "-c", f'. "$1"; {command}', "sh", str(env_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=repository,
    )
    deadline = time.monotonic() + ANSWERED_WITHIN_SECONDS
    while dana.identifier not in dana.on_standby():
        assert shell.poll() is None, f"the standby ended at once: {shell.communicate()}"
        assert time.monotonic() < deadline, "the standby was never held"
        time.sleep(CHECK_SECONDS / 2)

    answer_gate(owner, "emp-2", "agree", "Go ahead, I'm on the docs.")

    printed, errors = shell.communicate(timeout=ANSWERED_WITHIN_SECONDS)
    assert shell.returncode == 0, errors
    answer = json.loads(printed)
    assert answer["ended"] == "news", answer
    assert "agreed" in answer["message"] and "Go ahead, I'm on the docs." in answer["message"]


# Every other agent's background command (#527): Copilot in VS Code, Cursor and Copilot CLI copy it from AGENTS.md or
# Cursor's rule, with the personal token in SHARED_MEMORY_TOKEN as their hooks read it.


def background_standby(session: Session, shell: list[str], which: int) -> subprocess.Popen[str]:
    """Run the kit's background standby command for this session, as the agent copies it, in `shell`: the POSIX
    command (`which` 0) or the PowerShell one (1). Returns once the server holds the standby."""
    assert session.token is not None and session.project is not None and session.repository is not None
    files = connection_kit(
        server_url=session.server.url,
        marketplace="m",
        project_id=session.project,
        project_name="Billing",
        repository=session.repository,
    )
    (agents_md,) = [file["contents"] for file in files if file["path"] == "AGENTS.md"]
    command = background_standby_commands(agents_md)[which].replace("<session>", session.identifier)
    running = subprocess.Popen(
        [*shell, command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**without_the_token(), "SHARED_MEMORY_TOKEN": session.token},
    )
    deadline = time.monotonic() + ANSWERED_WITHIN_SECONDS
    while session.identifier not in session.on_standby():
        assert running.poll() is None, f"the standby ended at once: {running.communicate()}"
        assert time.monotonic() < deadline, "the standby was never held"
        time.sleep(CHECK_SECONDS / 2)
    return running


def printed_answer(running: subprocess.Popen[str]) -> dict[str, Any]:
    printed, errors = running.communicate(timeout=ANSWERED_WITHIN_SECONDS)
    assert running.returncode == 0, errors
    answer: dict[str, Any] = json.loads(printed)
    return answer


@pytest.mark.skipif(shutil.which("curl") is None, reason="the background command runs curl, which isn't installed")
def test_the_background_standby_command_run_in_a_posix_shell_hears_the_sessions_news(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    running = background_standby(dana, ["sh", "-c"], 0)

    answer_gate(owner, "emp-2", "agree", "Go ahead, I'm on the docs.")

    answer = printed_answer(running)
    assert answer["ended"] == "news", answer
    assert "agreed" in answer["message"] and "Go ahead, I'm on the docs." in answer["message"]


def test_a_session_with_no_hooks_that_stands_by_in_the_background_is_still_one_no_hook_reaches(
    team: Team, owner: Session, dana: Session
) -> None:
    """Copilot in VS Code stands by with the background command, but has no hook before an edit to refuse a gated
    one: a standby is not such a hook, so the session is still told its gate waits, in its tools' notices (#518)."""
    copilot = dana.as_agent("Visual Studio Code").as_session("copilot-session")
    copilot.call("set_activity", activity="Looking around", session=copilot.identifier)
    held = standing_by(copilot)
    team.server.clock.advance(minutes=5)
    assert answer_of(held)["ended"] == "nothing_yet"
    state(owner, WEBHOOKS)

    stated = "\n".join(copilot.call("set_activity", activity=RETRIES, session=copilot.identifier)["notices"])

    assert "[gated]" in stated and "no hook" in stated


@pytest.mark.skipif(not POWERSHELLS, reason="the background command for Windows runs in PowerShell, which isn't here")
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_the_background_standby_command_run_in_powershell_hears_the_sessions_news(
    owner: Session, dana: Session, shell: str
) -> None:
    collide(owner, dana)
    running = background_standby(dana, [shell, "-NoProfile", "-Command"], 1)

    answer_gate(owner, "emp-2", "agree", "Go ahead, I'm on the docs.")

    answer = printed_answer(running)
    assert answer["ended"] == "news", answer
    assert "agreed" in answer["message"] and "Go ahead, I'm on the docs." in answer["message"]


# Settings


def test_the_standby_settings_default_to_five_minutes_and_two_seconds() -> None:
    settings = Settings.from_env({})

    assert settings.standby_cap_minutes == 5
    assert settings.standby_check_seconds == 2


def test_the_stand_by_tools_cap_defaults_to_five_minutes() -> None:
    settings = Settings.from_env({})

    assert settings.standby_tool_cap_seconds == 300


def test_the_stand_by_tools_cap_reads_its_environment_variable() -> None:
    settings = Settings.from_env({"SHARED_MEMORY_STANDBY_TOOL_CAP_SECONDS": "120"})

    assert settings.standby_tool_cap_seconds == 120


def test_the_standby_settings_read_their_environment_variables() -> None:
    settings = Settings.from_env(
        {"SHARED_MEMORY_STANDBY_CAP_MINUTES": "3", "SHARED_MEMORY_STANDBY_CHECK_SECONDS": "0.5"}
    )

    assert settings.standby_cap_minutes == 3
    assert settings.standby_check_seconds == 0.5


def test_the_deployment_docs_and_the_compose_file_give_the_standby_settings_their_defaults() -> None:
    """A limit is named once: the docs and the compose file are static text, so this holds their defaults to the
    settings'."""
    settings = Settings.from_env({})
    compose = (REPO_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    docs = " ".join((REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8").split())

    for name, default in (
        ("SHARED_MEMORY_STANDBY_CAP_MINUTES", settings.standby_cap_minutes),
        ("SHARED_MEMORY_STANDBY_CHECK_SECONDS", settings.standby_check_seconds),
        ("SHARED_MEMORY_STANDBY_TOOL_CAP_SECONDS", settings.standby_tool_cap_seconds),
    ):
        assert f"{name}: ${{{name}:-{default:g}}}" in compose, name
        assert f"`{name}` (default {default:g}" in docs, name
    assert f"held {STAND_BY_SECONDS} seconds unless it asks for more" in docs
    assert (settings.standby_cap_minutes, settings.standby_check_seconds, settings.standby_tool_cap_seconds) == (
        Settings.standby_cap_minutes,
        Settings.standby_check_seconds,
        STAND_BY_TOOL_CAP_SECONDS,
    ), "the environment's defaults are the settings' own"
