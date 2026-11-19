"""The gate (ADR-0024): a later session's file edits are refused until the project's wait passes or its member says it
is different work. Reading still goes ahead, a member's own sessions never gate each other, and a gate ends with its
earlier session.

The collisions here are made as `test_collisions.py` makes them: Olive's session states an activity, and Dana's first
prompt scores 0.8 against it, so Dana's is the later session."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import (
    REPO_ROOT,
    Console,
    ConsoleClient,
    FakeGitHub,
    WORKING_FOLDER,
    RunningServer,
    Session,
    Team,
    TestClock,
    added_context,
    fresh_database,
    member,
    read_tool,
    search_tool,
)
from tests.test_before_edit import ALLOWED, reason_in
from tests.test_collisions import PROMPT, PROMPT_BELOW, RETRIES, WEBHOOKS, ChosenSimilarity, state, warnings
from tests.test_locks import FILE

GATED = "[gated]"
# What a notice that carries a warning says first, and how a warning is drawn: a bold heading over a fenced box.
SHOW_FIRST = "Show your member this first, word for word:"
WARNING = re.compile(r"\*\*(?P<heading>[^\n]+)\*\*\n\n```text\n(?P<box>.*?)\n```", re.DOTALL)


def warning_in(text: str) -> tuple[str, str]:
    """The heading and the box of the first warning in a notice."""
    found = WARNING.search(text)
    assert found is not None, f"no warning in {text!r}"
    return found["heading"], found["box"]


def after_warning(text: str) -> str:
    """What a notice tells the agent after its warning."""
    found = WARNING.search(text)
    assert found is not None, f"no warning in {text!r}"
    return text[found.end() :].strip()


def rows_in(box: str) -> list[str]:
    """The member rows of a warning's box, each as it opens."""
    return [line.strip("│ ") for line in box.splitlines() if line.startswith("│ - ")]


def columns(line: str) -> int:
    """The columns a line takes in a terminal."""
    return sum(
        0 if unicodedata.combining(each) else 2 if unicodedata.east_asian_width(each) in ("W", "F") else 1
        for each in line
    )


@pytest.fixture(scope="module")
def signing_in(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Console]:
    """This module's own server, in place of the one every other module shares, for the chosen embeddings, with a
    fake GitHub its members sign in to the console through, to choose their time zone."""
    memory = tmp_path_factory.mktemp("gates-memory")
    with start_blocking_portal() as portal:
        github = FakeGitHub(portal, Settings("", memory, memory))
        settings = Settings(
            database_url=fresh_database("shared_memory_gates"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=github.url,
            github_api_url=github.url,
            rate_limit_on=False,
        )
        clock = TestClock()
        embedder = ChosenSimilarity(settings.model_cache)
        running = RunningServer(build_app(settings, clock=clock, embedder=embedder), settings, clock, portal)
        try:
            yield Console(running, github, clock)
        finally:
            running.stop()
            github.stop()


@pytest.fixture(scope="module")
def server(signing_in: Console) -> RunningServer:
    return signing_in.server


def collide(earlier: Session, later: Session) -> None:
    """Make a collision with `later` as the later session: its first prompt is nearly the earlier one's activity."""
    state(earlier, WEBHOOKS)
    assert warnings(later, PROMPT), "the prompt collides"


def different_work(session: Session) -> dict[str, Any]:
    answer: dict[str, Any] = session.call("different_work", session=session.identifier)
    return answer


def denied(answer: dict[str, Any]) -> bool:
    """Whether a before-edit hook's answer stops the edit, whatever news it carries."""
    return bool(answer.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")


def read_of(session: Session) -> dict[str, Any]:
    """The before-edit hook for a tool that only reads a file, as Copilot CLI sends it."""
    viewed = {"sessionId": session.identifier, "cwd": WORKING_FOLDER, "toolName": "view", "toolArgs": {"path": FILE}}
    return session.hook_payload("before-edit", viewed, "copilot-cli")


# Gated


def test_a_later_sessions_edit_is_refused_naming_who_their_activity_the_time_left_and_different_work(
    owner: Session, dana: Session
) -> None:
    collide(owner.as_agent("claude-code"), dana)

    answer = dana.edit(FILE)

    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = reason_in(answer)
    first_line = after_warning(reason).splitlines()[0]
    assert first_line.startswith(GATED)
    assert "different work" in first_line and "different_work" in first_line
    assert "Olive Owner" in reason
    assert "Claude Code" in reason
    assert f'"{WEBHOOKS}"' in reason
    assert "5 minutes left" in reason
    assert "ask your member" in reason


# The warnings (#586)


def test_before_edit_hook_refusal_for_a_gated_session_carries_the_warning_one_row_per_earlier_member(
    owner: Session, cole: Session, dana: Session
) -> None:
    state(owner, WEBHOOKS)
    state(owner.as_session("olive-second"), WEBHOOKS)
    state(cole, WEBHOOKS)
    assert warnings(dana, PROMPT), "the prompt collides"

    reason = reason_in(dana.edit(FILE))

    assert reason.startswith(SHOW_FIRST)
    heading, box = warning_in(reason)
    assert heading in ("⚠ Your edit waits for Olive Owner and Cole Coder", "⚠ Your edit waits for Cole Coder and Olive Owner")
    rows = sorted(rows_in(box))
    assert len(rows) == 2, "one row per member, not per session"
    assert rows[0].startswith(f'- Cole Coder, working on "{WEBHOOKS}"')
    assert rows[1].startswith(f'- Olive Owner, working on "{WEBHOOKS}"')
    said = " ".join(line.strip("│ ") for line in box.splitlines())
    assert "5 min left" in said
    assert "Your session stands by" in said
    assert "wait · different work · pick something else" in said


def test_a_refused_member_shows_as_refused_in_the_held_members_warning(
    team: Team, owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse")
    team.server.clock.advance(minutes=6)

    _, box = warning_in(reason_in(dana.edit(FILE)))

    (row,) = rows_in(box)
    assert row.startswith("- Olive Owner") and "refused" in row
    assert "min left" not in box, "a refusal holds past the wait"


def test_the_earlier_sessions_gate_notice_carries_the_warning_told_once(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    told = heard(owner)

    assert SHOW_FIRST in told
    heading, box = warning_in(told)
    assert heading == "⚠ Dana Dev is waiting on you"
    said = " ".join(line.strip("│ ") for line in box.splitlines())
    assert "Its edits wait for your answer" in said
    assert "5 min left" in said
    assert "agree · refuse" in said
    again = heard(owner)
    assert SHOW_FIRST not in again and "Dana Dev" not in again, "told once"


def test_the_box_is_a_text_fence_hard_wrapped_at_60_columns_with_no_gendered_pronouns_and_no_utc(
    team: Team, project: str, dana: Session
) -> None:
    wide = member(team, project, "emp-9", "山田花子 Wolfeschlegelsteinhausenbergerdorffvoralternwarengewissenhaft ```")
    collide(wide, dana)

    reason = reason_in(dana.edit(FILE))
    told = heard(wide)

    for notice in (reason, told):
        heading, box = warning_in(notice)
        lines = box.splitlines()
        assert lines[0].startswith("┌") and lines[-1].startswith("└")
        assert all(columns(line) == 60 for line in lines), "every line of the box is exactly 60 columns"
        assert all(line.startswith("│") and line.endswith("│") for line in lines[1:-1])
        assert "```" not in box, "a teammate's words cannot close the fence"
        whole = f"{heading}\n{box}"
        assert not re.search(r"\b(he|she|him|her|his|hers|himself|herself)\b", whole, re.IGNORECASE)
        assert "UTC" not in whole and "+00:00" not in whole and "09:05" not in whole


# Local times (#591): a warning gives the clock time in its reader's time zone, the one they chose in the console, else
# the one their browser reported, and stays relative with none. The gate here is found at 09:00 UTC and its wait of 5
# minutes passes at 09:05 UTC.


def in_time_zone(
    signing_in: Console,
    team: Team,
    member_id: str,
    github: str,
    account: int,
    detected: str | None = None,
    chosen: str | None = None,
) -> None:
    """A member signs in to the console, whose browser reports `detected`, and chooses `chosen`."""
    team.server.run_cli("link-github", "--team", team.code, "--member-id", member_id, "--github", github)
    signing_in.github.as_(account, github)
    client: ConsoleClient = signing_in.client()
    try:
        client.sign_in()
        if detected is not None:
            assert client.post_json("/api/my-time-zone/detected", {"time_zone": detected}).status_code == 200
        if chosen is not None:
            assert client.post_json("/api/my-time-zone", {"time_zone": chosen}).status_code == 200
    finally:
        client.close()


def warning_says(notice: str) -> str:
    """What a notice's warning box says, its lines joined back up."""
    _, box = warning_in(notice)
    return " ".join(line.strip("│ ") for line in box.splitlines())


def test_a_held_members_warning_gives_the_clock_time_in_the_time_zone_they_chose(
    signing_in: Console, team: Team, owner: Session, dana: Session
) -> None:
    in_time_zone(signing_in, team, "emp-2", "dana-zone-chosen", 5921, detected="America/New_York", chosen="Asia/Kolkata")
    collide(owner, dana)

    said = warning_says(reason_in(dana.edit(FILE)))

    assert "5 min left (until 2:35 pm your time)" in said


def test_a_held_members_warning_gives_the_clock_time_in_the_time_zone_detected_for_them(
    signing_in: Console, team: Team, owner: Session, dana: Session
) -> None:
    in_time_zone(signing_in, team, "emp-2", "dana-zone-detected", 5922, detected="America/New_York")
    collide(owner, dana)

    said = warning_says(reason_in(dana.edit(FILE)))

    assert "5 min left (until 5:05 am your time)" in said


def test_the_asked_members_warning_gives_the_clock_time_in_their_own_time_zone(
    signing_in: Console, team: Team, owner: Session, dana: Session
) -> None:
    in_time_zone(signing_in, team, "owner-1", "olive-zone-asked", 5923, chosen="Europe/Berlin")
    in_time_zone(signing_in, team, "emp-2", "dana-zone-asked", 5924, chosen="Asia/Kolkata")
    collide(owner, dana)

    said = warning_says(heard(owner))

    assert "5 min left (until 11:05 am your time)" in said, "Olive's zone, not Dana's"


def test_a_warning_stays_relative_for_a_reader_with_no_time_zone(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    held, asked = warning_says(reason_in(dana.edit(FILE))), warning_says(heard(owner))

    for said in (held, asked):
        assert "5 min left" in said
        assert "your time" not in said and "am" not in said.split() and "pm" not in said.split()


def test_a_standby_that_hears_nothing_gives_the_clock_time_in_its_members_time_zone(
    signing_in: Console, team: Team, dana: Session
) -> None:
    in_time_zone(signing_in, team, "emp-2", "dana-zone-standby", 5925, chosen="Asia/Kolkata")
    dana.start()

    answer = dana.call("stand_by", session=dana.identifier, seconds=0)

    assert answer["ended"] == "nothing_yet"
    assert "5 min left (until 2:35 pm your time)" in warning_says(answer["member"])
    assert answer["member"] in answer["message"]


def test_a_standbys_news_gives_the_clock_time_in_the_time_zone_of_the_member_standing_by(
    signing_in: Console, team: Team, owner: Session, dana: Session
) -> None:
    in_time_zone(signing_in, team, "owner-1", "olive-zone-standby", 5926, chosen="Europe/Berlin")
    in_time_zone(signing_in, team, "emp-2", "dana-zone-standby-news", 5927, chosen="Asia/Kolkata")
    collide(owner, dana)

    answer = owner.call("stand_by", session=owner.identifier, seconds=0)

    assert answer["ended"] == "news"
    said = warning_says(answer["member"])
    assert "5 min left (until 11:05 am your time)" in said, "Olive reads it, so Olive's zone, not Dana's"


def test_agent_only_instructions_still_follow_the_warning(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    refused = after_warning(reason_in(dana.edit(FILE)))
    asked = after_warning(heard(owner))

    assert refused.startswith(GATED) and "different_work" in refused and "ask your member" in refused
    assert asked.startswith("[gate] Dana Dev (emp-2)") and "answer_gate" in asked and '"emp-2"' in asked
    assert "never on your own judgment" in asked


# The headline Claude Code shows its member itself (#587)

# The formats other than Claude Code's, each told its news by the hook it hears news in.
OTHER_FORMATS = ["gemini", "devin", "copilot-cli", "cursor", "cline"]


def test_claude_code_format_carries_the_headline_with_the_gate_warning_on_both_members_notices(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)

    refused = dana.edit(FILE)
    told = owner.use(search_tool("webhook"))

    assert warning_in(reason_in(refused))[0] == "⚠ Your edit waits for Olive Owner"
    assert refused["systemMessage"] == "⚠ Your edit waits for Olive Owner. Read the box below."
    assert warning_in(added_context(told))[0] == "⚠ Dana Dev is waiting on you"
    assert told["systemMessage"] == "⚠ Dana Dev is waiting on you. Read the box below."
    assert "systemMessage" not in owner.use(search_tool("webhook")), "once per notice"


def test_a_second_refusal_of_the_same_gate_keeps_the_warning_without_the_headline(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    first = dana.edit(FILE)

    second = dana.edit(FILE)

    assert "systemMessage" in first
    assert denied(second)
    assert warning_in(reason_in(second))[0] == "⚠ Your edit waits for Olive Owner"
    assert "systemMessage" not in second


@pytest.mark.parametrize("format", OTHER_FORMATS)
def test_other_formats_get_no_system_message(owner: Session, dana: Session, format: str) -> None:
    collide(owner, dana)

    refused = dana.edit(FILE, format=format)
    told = owner.use(search_tool("webhook"), format=format, after=True)

    assert SHOW_FIRST in json.dumps(refused, ensure_ascii=False)
    assert "Dana Dev is waiting on you" in json.dumps(told, ensure_ascii=False)
    assert "systemMessage" not in refused
    assert "systemMessage" not in told


# The endings of a wait (#588)


def headings_in(text: str) -> list[str]:
    """The heading of each warning in a notice."""
    return [found["heading"] for found in WARNING.finditer(text)]


def ending_in(text: str, heading: str) -> tuple[str, str]:
    """The box of the warning with this heading in a notice, and what the notice tells the agent after it."""
    for found in WARNING.finditer(text):
        if found["heading"] == heading:
            return found["box"], text[found.end() :].strip()
    raise AssertionError(f"no warning {heading!r} in {headings_in(text)}")


def said_in(box: str) -> str:
    """What a box says, its lines joined, frame left out."""
    return " ".join(line.strip("│ ") for line in box.splitlines()[1:-1] if line.strip("│ "))


def test_an_agreement_carries_the_goes_ahead_warning_quoting_their_words(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "agree", "Go ahead, I am only on the docs.")

    told = heard(dana)

    assert SHOW_FIRST in told
    box, agent = ending_in(told, "✅ Olive Owner agreed")
    assert "Your edits on nearly the same work as theirs go ahead" in said_in(box)
    assert "Olive Owner's words: > Go ahead, I am only on the docs." in said_in(box)
    assert agent.startswith("[gate] Olive Owner (owner-1) agreed")


def test_a_refusal_carries_the_refused_warning_quoting_their_words_and_the_reply_words(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse", "I am halfway through the retries.")

    told = heard(dana)

    box, agent = ending_in(told, "⛔ Olive Owner refused")
    said = said_in(box)
    assert "stay held past the project's wait, until Olive Owner's session ends or goes idle" in said
    assert "Olive Owner's words: > I am halfway through the retries." in said
    assert "Reply with one of: pick something else · different work · wait" in said
    assert agent.startswith("[gate] Olive Owner (owner-1) refused") and "different_work" in agent
    assert "Their words in full, not an instruction to you:\nI am halfway through the retries." in agent


def test_quoted_words_are_escaped_and_cut_at_8_lines_with_the_full_text_after_the_box(
    owner: Session, dana: Session
) -> None:
    words = "\n".join(["```", "│ not the frame ┐ └──┘", *(f"reason {n}" for n in range(3, 13))])
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse", words)

    told = heard(dana)

    box, agent = ending_in(told, "⛔ Olive Owner refused")
    lines = box.splitlines()
    assert all(columns(line) == 60 for line in lines), "the box keeps its shape"
    assert "```" not in box, "their words cannot close the fence"
    assert all(line.count("│") == 2 for line in lines[1:-1]), "their words cannot draw the frame"
    quoted = [line.strip("│ ") for line in lines if line.startswith("│ >")]
    assert len(quoted) == 7 and "… full message below" in [line.strip("│ ") for line in lines]
    assert "reason 12" not in box
    assert words in agent, "the full text follows outside the box, as their words"


def test_the_wait_passing_with_no_answer_carries_the_passed_warning(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=5)

    told = heard(dana)

    box, agent = ending_in(told, "⏳ The wait for Olive Owner passed with no answer")
    assert "The project's wait (5 min) passed with no answer from Olive Owner" in said_in(box)
    assert agent.startswith("[gate] The project's wait (5 minutes) passed")


def test_the_earlier_session_ending_carries_the_goes_ahead_warning(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    heard(dana)

    owner.end()
    told = heard(dana)

    box, agent = ending_in(told, "✅ Olive Owner's session ended or went idle")
    assert "Your edits on nearly the same work as theirs go ahead" in said_in(box)
    assert agent.startswith("[gate] Olive Owner's session ended or went idle")


def test_the_earlier_member_is_warned_when_the_gated_teammate_says_it_is_different_work(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    different_work(dana)

    told = heard(owner)

    box, agent = ending_in(told, "✅ Dana Dev said it is different work")
    assert "their edits go ahead now, near your work" in said_in(box)
    assert agent.startswith("[gate] Dana Dev's session")


def test_the_earlier_member_is_warned_when_the_gated_teammate_goes_ahead_on_the_wait(
    team: Team, owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    heard(owner)
    team.server.clock.advance(minutes=5)

    told = heard(owner)

    box, _ = ending_in(told, "⏳ Dana Dev went ahead on the wait")
    assert "The project's wait (5 min) passed with no answer, so their edits go ahead now" in said_in(box)


def test_ending_warnings_have_no_gendered_pronouns_and_no_utc(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse", "Not yet.")
    refused = heard(dana)
    answer_gate(owner, "emp-2", "agree")
    agreed = heard(dana)

    for notice in (refused, agreed):
        for found in WARNING.finditer(notice):
            whole = f"{found['heading']}\n{found['box']}"
            assert not re.search(r"\b(he|she|him|her|his|hers|himself|herself)\b", whole, re.IGNORECASE)
            assert "UTC" not in whole and "+00:00" not in whole


def test_claude_code_format_carries_the_headline_with_each_ending_warning(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse", "Not yet.")

    told = dana.use(search_tool("webhook"))

    assert told["systemMessage"] == "⛔ Olive Owner refused. Read the box below."
    assert "systemMessage" not in dana.use(search_tool("webhook")), "once per notice"


@pytest.mark.parametrize("format", OTHER_FORMATS)
def test_other_formats_get_the_ending_warning_with_no_system_message(
    owner: Session, dana: Session, format: str
) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "agree")

    told = dana.use(search_tool("webhook"), format=format, after=True)

    assert "Olive Owner agreed" in json.dumps(told, ensure_ascii=False)
    assert "systemMessage" not in told


def test_a_gated_session_may_still_read(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    assert read_of(dana) == ALLOWED


def test_a_gated_edit_takes_no_lock(owner: Session, dana: Session, cole: Session) -> None:
    collide(owner, dana)
    dana.edit(FILE)

    assert cole.edit(FILE) == ALLOWED, "the refused edit left the file free"


def test_the_time_left_counts_down(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=3)

    assert "2 minutes left" in reason_in(dana.edit(FILE))


def test_the_earlier_session_is_not_gated(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    assert not denied(owner.edit("src/other.py")), "told of the gate, never stopped by it"


def test_a_prompt_that_does_not_collide_gates_nothing(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    warnings(dana, PROMPT_BELOW)

    assert dana.edit(FILE) == ALLOWED


# Lifted


def test_once_the_wait_has_passed_the_edit_goes_ahead(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=4, seconds=59)
    assert GATED in reason_in(dana.edit(FILE))

    team.server.clock.advance(seconds=1)

    assert dana.edit(FILE) == ALLOWED


def test_a_gated_edit_carries_no_tied_memory_and_leaves_it_untold(team: Team, owner: Session, dana: Session) -> None:
    path = dana.call(
        "remember",
        title="Invoice numbers are never reused",
        summary="An invoice number is never given out twice.",
        type="gotcha",
        body="A voided invoice keeps its number for good.",
        tied_files=[f"billing-api:{FILE}"],
    )["path"]
    collide(owner, dana)

    reason = reason_in(dana.edit(FILE))
    team.server.clock.advance(minutes=5)
    allowed = dana.edit(FILE)

    assert GATED in reason and path not in reason and "<memory-" not in reason
    assert path in allowed["hookSpecificOutput"]["additionalContext"], "given on the first edit that goes ahead"


def test_different_work_lifts_the_gate_at_once(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    lifted = different_work(dana)

    assert lifted["lifted"] == ["Olive Owner"]
    assert dana.edit(FILE) == ALLOWED


def test_the_earlier_session_is_told_of_different_work_once_on_its_next_prompt(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    different_work(dana)

    told = added_context(owner.prompt("write a haiku about cats"))

    assert "Dana Dev" in told and "different work" in told
    assert "different work" not in added_context(owner.prompt("write a haiku about cats")), "told once"


def test_the_earlier_session_is_told_when_the_wait_ran_out(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=5)
    dana.edit(FILE)

    told = added_context(owner.prompt("write a haiku about cats"))

    assert "Dana Dev" in told and "wait" in told


def test_different_work_on_a_session_that_is_not_gated_lifts_nothing(dana: Session) -> None:
    assert different_work(dana)["lifted"] == []


def test_a_gate_ends_when_its_earlier_session_ends(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    owner.end()

    assert dana.edit(FILE) == ALLOWED


def test_a_gate_ends_when_its_earlier_session_goes_idle(team: Team, owner: Session, dana: Session) -> None:
    owner.call("project_wait", minutes=60)
    collide(owner, dana)
    team.server.clock.advance(minutes=20)
    assert GATED in reason_in(dana.edit(FILE)), "Dana's session stays active"

    team.server.clock.advance(minutes=11)

    assert dana.edit(FILE) == ALLOWED, "Olive's session made no call for 31 minutes"


# Own sessions


def test_a_members_own_sessions_warn_each_other_but_never_gate(owner: Session) -> None:
    second = owner.as_session("second-session")
    state(owner, WEBHOOKS)

    assert warnings(second, PROMPT), "warned"
    assert second.edit(FILE) == ALLOWED, "never gated"


# The project's wait


def payments(team: Team, dana: Session) -> tuple[Session, Session, Session]:
    """A project Dana created, so she leads it, with Cole working in it and the team's owner, an admin who doesn't
    lead it."""
    project = dana.call("create_project", name="Payments")["project_id"]
    cole = member(team, project, "emp-3", "Cole Coder").in_project(project, "payments-api")
    return dana.in_project(project, "payments-api"), cole, team.owner().in_project(project, "payments-api")


def test_the_wait_is_five_minutes_unless_the_project_says_otherwise(owner: Session) -> None:
    assert owner.call("project_wait") == {"minutes": 5}


def test_a_lead_sets_the_projects_wait_and_it_holds_the_gate_that_long(team: Team, dana: Session) -> None:
    lead, cole, admin = payments(team, dana)

    changed = lead.call("project_wait", minutes=12)
    collide(admin, cole)
    team.server.clock.advance(minutes=10)

    assert changed == {"minutes": 12}
    assert cole.call("project_wait") == {"minutes": 12}, "any member reads it"
    assert "2 minutes left" in reason_in(cole.edit(FILE))


def test_an_admin_sets_the_wait_too(team: Team, dana: Session) -> None:
    _, _, admin = payments(team, dana)

    assert admin.call("project_wait", minutes=2) == {"minutes": 2}


def test_a_member_who_is_not_a_lead_cannot_set_the_wait(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)

    refused = cole.refusal("project_wait", minutes=1)

    assert "leads" in refused and "admins" in refused
    assert lead.call("project_wait") == {"minutes": 5}


def test_a_wait_out_of_bounds_is_refused(owner: Session) -> None:
    assert "minutes" in owner.refusal("project_wait", minutes=0)
    assert "minutes" in owner.refusal("project_wait", minutes=24 * 60 + 1)


# The audit log


def gate_entries(server: RunningServer, project: str) -> list[tuple[str, str, dict[str, Any]]]:
    """The project's gate entries in the audit log: kind, actor and detail, oldest first."""
    with psycopg.connect(server.settings.database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT kind, actor, detail FROM audit_events WHERE project_id = %s"
            " AND kind IN ('gate_timed_out', 'different_work', 'project_wait_changed') ORDER BY id",
            (project,),
        ).fetchall()
    return [(kind, actor, detail) for kind, actor, detail in rows]


def test_different_work_and_a_timeout_are_in_the_audit_log_with_the_score_and_no_prompt(
    team: Team, owner: Session, dana: Session, cole: Session
) -> None:
    collide(owner, dana)
    warnings(cole, PROMPT)
    different_work(dana)
    team.server.clock.advance(minutes=5)
    cole.edit(FILE)
    cole.edit(FILE)

    entries = gate_entries(team.server, owner.project or "")

    assert entries == [
        ("different_work", "emp-2", {"earlier": "owner-1", "score": 0.8, "cause": "prompt"}),
        ("gate_timed_out", "emp-3", {"earlier": "owner-1", "score": 0.8, "cause": "prompt"}),
    ], "each recorded once"
    assert PROMPT not in str(entries)


def test_a_change_to_the_wait_is_in_the_audit_log(team: Team, dana: Session) -> None:
    lead, _, _ = payments(team, dana)

    lead.call("project_wait", minutes=12)

    assert gate_entries(team.server, lead.project or "") == [("project_wait_changed", "emp-2", {"minutes": 12})]


# The earlier member's answer (#512)


def answer_gate(session: Session, member: str, answer: str, text: str | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {"session": session.identifier, "member": member, "answer": answer}
    if text is not None:
        arguments["text"] = text
    answered: dict[str, Any] = session.call("answer_gate", **arguments)
    return answered


def heard(session: Session) -> str:
    """What the session hears on its next tool call, in Claude Code's hook before a tool."""
    return added_context(session.use(search_tool("webhook")))


def test_the_earlier_session_is_told_once_that_a_later_session_is_gated_on_its_work_and_how_to_answer(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)

    told = heard(owner)

    assert "[gate]" in told and "Dana Dev (emp-2)" in told
    assert "answer_gate" in told and '"emp-2"' in told
    assert "ask your member" in told
    assert "Dana Dev" not in heard(owner), "told once"


def test_agree_lifts_the_gate_and_the_later_session_hears_it(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    answered = answer_gate(owner, "emp-2", "agree", "Go ahead, I am only on the docs.")
    told = heard(dana)

    assert answered["answered"] == ["Dana Dev"]
    assert "Olive Owner (owner-1)" in told and "agreed" in told
    assert "Go ahead, I am only on the docs." in told
    assert dana.edit(FILE) == ALLOWED
    assert "agreed" not in heard(dana), "heard once"


def test_refuse_keeps_the_gate_past_the_wait_and_the_later_session_hears_it(
    team: Team, owner: Session, dana: Session
) -> None:
    collide(owner, dana)

    answer_gate(owner, "emp-2", "refuse", "I am halfway through the retries.")
    told = heard(dana)
    team.server.clock.advance(minutes=6)
    reason = reason_in(dana.edit(FILE))

    assert "Olive Owner (owner-1)" in told and "refused" in told
    assert "I am halfway through the retries." in told
    assert after_warning(reason).startswith(GATED) and "refused" in reason


def test_a_refusal_holds_until_the_refusing_session_ends(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse")
    team.server.clock.advance(minutes=10)
    assert GATED in reason_in(dana.edit(FILE))

    owner.end()

    assert not denied(dana.edit(FILE))


def test_a_refusal_holds_until_the_refusing_session_goes_idle(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse")
    team.server.clock.advance(minutes=20)
    assert GATED in reason_in(dana.edit(FILE)), "Dana's session stays active"

    team.server.clock.advance(minutes=11)

    assert not denied(dana.edit(FILE)), "Olive's session made no call for 31 minutes"


def test_a_refusal_may_be_changed_to_agree(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse")
    heard(dana)

    answer_gate(owner, "emp-2", "agree")

    assert "agreed" in heard(dana)
    assert dana.edit(FILE) == ALLOWED


def test_an_agreement_cannot_be_turned_into_a_refusal(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "agree")

    refused = owner.refusal("answer_gate", session=owner.identifier, member="emp-2", answer="refuse")

    assert "agreed" in refused


def two_earlier(owner: Session, cole: Session, dana: Session) -> None:
    """Olive's and Cole's sessions both on the webhooks, and Dana's first prompt nearly the same: Dana's session is the
    later one to both."""
    state(owner, WEBHOOKS)
    state(cole, WEBHOOKS)
    assert len(warnings(dana, PROMPT)) == 2, "the prompt collides with both"


def test_with_two_earlier_sessions_one_agreeing_keeps_the_gate_until_the_other_agrees(
    owner: Session, cole: Session, dana: Session
) -> None:
    two_earlier(owner, cole, dana)

    answer_gate(owner, "emp-2", "agree")
    still = reason_in(dana.edit(FILE))
    answer_gate(cole, "emp-2", "agree")
    heard(dana)

    assert after_warning(still).startswith(GATED) and "Cole Coder" in still and "Olive Owner" not in still
    assert dana.edit(FILE) == ALLOWED


def test_with_two_earlier_sessions_one_agreeing_and_the_other_silent_lifts_once_the_wait_passes(
    team: Team, owner: Session, cole: Session, dana: Session
) -> None:
    two_earlier(owner, cole, dana)
    answer_gate(owner, "emp-2", "agree")
    team.server.clock.advance(minutes=4)
    assert GATED in reason_in(dana.edit(FILE)), "Cole has not answered and the wait runs"

    team.server.clock.advance(minutes=1)

    assert not denied(dana.edit(FILE))


def test_with_two_earlier_sessions_one_refusal_keeps_the_gate(
    team: Team, owner: Session, cole: Session, dana: Session
) -> None:
    two_earlier(owner, cole, dana)
    answer_gate(owner, "emp-2", "agree")
    answer_gate(cole, "emp-2", "refuse")
    team.server.clock.advance(minutes=6)

    reason = reason_in(dana.edit(FILE))

    assert after_warning(reason).startswith(GATED) and "Cole Coder" in reason and "refused" in reason
    assert "Olive Owner" not in reason


def test_only_the_earlier_sessions_own_member_can_answer(owner: Session, dana: Session, cole: Session) -> None:
    collide(owner, dana)

    by_another = cole.refusal("answer_gate", session=owner.identifier, member="emp-2", answer="agree")
    by_the_later = dana.refusal("answer_gate", session=dana.identifier, member="emp-2", answer="agree")

    assert "No gate" in by_another and "No gate" in by_the_later
    assert GATED in reason_in(dana.edit(FILE)), "still gated"


def test_an_answer_after_the_wait_has_passed_is_refused(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=5)

    refused = owner.refusal("answer_gate", session=owner.identifier, member="emp-2", answer="refuse")

    assert "wait" in refused
    assert dana.edit(FILE) == ALLOWED


def test_an_answer_other_than_agree_or_refuse_is_refused(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    refused = owner.refusal("answer_gate", session=owner.identifier, member="emp-2", answer="maybe")

    assert '"agree"' in refused and '"refuse"' in refused


def answer_entries(server: RunningServer, project: str) -> list[tuple[str, str, str, dict[str, Any]]]:
    """The project's agree and refuse entries in the audit log: kind, actor, target and detail, oldest first."""
    with psycopg.connect(server.settings.database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT kind, actor, target, detail FROM audit_events WHERE project_id = %s"
            " AND kind IN ('gate_agreed', 'gate_refused') ORDER BY id",
            (project,),
        ).fetchall()
    return [(kind, actor, target, detail) for kind, actor, target, detail in rows]


def test_agree_and_refuse_are_in_the_audit_log_with_the_score_and_no_text(
    team: Team, owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    answer_gate(owner, "emp-2", "refuse", "Not yet, please.")
    answer_gate(owner, "emp-2", "agree", "Fine, go ahead.")

    entries = answer_entries(team.server, owner.project or "")

    assert entries == [
        ("gate_refused", "owner-1", "emp-2", {"later": "emp-2", "score": 0.8, "cause": "prompt"}),
        ("gate_agreed", "owner-1", "emp-2", {"later": "emp-2", "score": 0.8, "cause": "prompt"}),
    ]
    assert "Not yet" not in str(entries) and "go ahead" not in str(entries)


# Urgent messages (#513)

URGENT = "Please hold the webhook retries: the gateway's contract changed this morning."


def send_urgent(session: Session, to: str, text: str = URGENT) -> dict[str, Any]:
    sent: dict[str, Any] = session.call("send_message", session=session.identifier, to=to, text=text, urgent=True)
    return sent


def refused_urgent(session: Session, to: str, text: str = URGENT) -> str:
    return session.refusal("send_message", session=session.identifier, to=to, text=text, urgent=True)


def test_an_urgent_message_gates_the_earlier_sessions_edit_until_its_member_answers(
    owner: Session, dana: Session
) -> None:
    collide(owner, dana)

    send_urgent(dana, "owner-1")
    told = heard(owner)
    reason = reason_in(owner.edit("src/other.py"))

    assert "urgent" in told and URGENT in told
    first_line = reason.splitlines()[0]
    assert first_line.startswith(GATED) and "urgent" in first_line and "different_work" in first_line
    assert "Dana Dev (emp-2)" in reason and "5 minutes left" in reason
    assert "send_message" in reason

    owner.call("send_message", session=owner.identifier, to="emp-2", text="Holding off; tell me when it is settled.")

    assert not denied(owner.edit("src/other.py")), "its member answered"


def test_an_answer_to_the_gate_answers_the_urgent_message_too(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    answer_gate(owner, "emp-2", "agree")

    assert not denied(owner.edit("src/other.py"))


def test_without_an_answer_the_wait_lifts_an_urgent_messages_gate(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=2)
    send_urgent(dana, "owner-1")
    team.server.clock.advance(minutes=4, seconds=59)
    assert GATED in reason_in(owner.edit("src/other.py")), "the wait runs from the urgent message"

    team.server.clock.advance(seconds=1)

    assert not denied(owner.edit("src/other.py"))


def test_different_work_lifts_an_urgent_messages_gate(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    lifted = different_work(owner)

    assert lifted["lifted"] == ["Dana Dev"]
    assert not denied(owner.edit("src/other.py"))


def test_a_second_urgent_message_on_the_same_collision_is_refused(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    refused = refused_urgent(dana, "owner-1", "Really, please hold.")

    assert "urgent" in refused and "one" in refused
    assert dana.call("send_message", session=dana.identifier, to="owner-1", text="Really, please hold.")["to"] == (
        "Olive Owner"
    ), "a message that is not urgent still goes"


def test_an_urgent_message_needs_a_collision_between_the_two_sessions(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()

    refused = refused_urgent(dana, "owner-1")

    assert "collision" in refused
    assert not denied(owner.edit("src/other.py"))
    assert URGENT not in heard(owner), "nothing was sent"


def test_only_the_later_session_sends_an_urgent_message(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    refused = refused_urgent(owner, "emp-2")

    assert "later" in refused
    assert not denied(owner.edit("src/other.py"))


def test_an_urgent_messages_gate_ends_when_its_later_session_ends(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    dana.end()

    assert not denied(owner.edit("src/other.py"))


def test_each_urgent_message_is_in_the_audit_log_without_its_text(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    with psycopg.connect(team.server.settings.database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT kind, actor, target, detail FROM audit_events WHERE project_id = %s AND kind = 'urgent_message'",
            (owner.project or "",),
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("urgent_message", "emp-2", "owner-1", {"earlier": "owner-1", "score": 0.8, "cause": "prompt"})
    ]
    assert URGENT not in str(rows)


# Agents with no hooks (#518)


def copilot_in_vs_code(session: Session) -> Session:
    """The same member's session as Copilot in VS Code makes it: tool calls only, since no hook of its runs."""
    return session.as_agent("Visual Studio Code").as_session("copilot-session")


def notices_of(answer: dict[str, Any]) -> str:
    return "\n".join(answer["notices"])


def test_a_session_no_hook_reaches_is_told_in_its_next_tool_result_once_that_its_edits_wait(
    owner: Session, dana: Session
) -> None:
    copilot = copilot_in_vs_code(dana)
    state(owner, WEBHOOKS)

    stated = copilot.call("set_activity", activity=RETRIES, session=copilot.identifier)["notices"]
    again = notices_of(copilot.call("take_lock", path="docs/retries.md", session=copilot.identifier))

    (gated,) = [notice for notice in stated if notice.startswith(GATED)]
    first_line = gated.splitlines()[0]
    assert "different work" in first_line and "different_work" in first_line
    assert "no hook" in gated
    assert "Olive Owner" in gated and f'"{WEBHOOKS}"' in gated and "5 minutes left" in gated
    assert "ask your member" in gated
    assert GATED not in again, "told once"


def test_a_session_a_hook_has_reached_hears_of_its_gate_when_an_edit_is_refused_not_in_its_tool_results(
    owner: Session, dana: Session
) -> None:
    dana.start()
    state(owner, WEBHOOKS)

    stated = notices_of(dana.call("set_activity", activity=RETRIES, session=dana.identifier))

    assert GATED not in stated
    assert GATED in reason_in(dana.edit(FILE))


def test_a_session_no_hook_reaches_hears_messages_and_gate_answers_in_its_next_tool_result_once(
    owner: Session, dana: Session
) -> None:
    copilot = copilot_in_vs_code(dana)
    state(owner, WEBHOOKS)
    copilot.call("set_activity", activity=RETRIES, session=copilot.identifier)
    answer_gate(owner, "emp-2", "refuse", "I am halfway through the retries.")
    owner.call("send_message", session=owner.identifier, to="emp-2", text="Take the back end?")

    told = notices_of(copilot.call("mute", session=copilot.identifier, on=False))
    again = notices_of(copilot.call("mute", session=copilot.identifier, on=False))

    assert "Olive Owner (owner-1) refused" in told and "I am halfway through the retries." in told
    assert "[message]" in told and "Take the back end?" in told
    assert again == "", "each heard once"


def test_the_earlier_session_no_hook_reaches_is_told_in_its_next_tool_result_that_a_gate_waits_on_its_work(
    owner: Session, dana: Session
) -> None:
    copilot = copilot_in_vs_code(owner)
    state(copilot, WEBHOOKS)
    collided = warnings(dana, PROMPT)

    told = notices_of(copilot.call("set_activity", activity=WEBHOOKS, session=copilot.identifier))

    assert collided
    assert "[gate]" in told and "Dana Dev (emp-2)" in told and "answer_gate" in told


# A timeout is kept when either side reads it (#507 stories 17, 31), so a later session that stays quiet is still
# recorded and the earlier member still told.


def test_a_timeout_is_kept_and_told_when_the_earlier_session_hears_it_though_the_later_one_stays_quiet(
    team: Team, owner: Session, dana: Session
) -> None:
    collide(owner, dana)
    heard(owner)
    team.server.clock.advance(minutes=5)

    told = heard(owner)

    assert "Dana Dev's session" in told and "with no answer and goes ahead" in told
    assert gate_entries(team.server, owner.project or "") == [
        ("gate_timed_out", "emp-2", {"earlier": "owner-1", "score": 0.8, "cause": "prompt"}),
    ], "recorded once, as the later member's"
    assert "with no answer" not in heard(owner), "told once"


def test_a_refused_edit_names_the_earlier_sessions_branch_and_the_files_it_touched(owner: Session, dana: Session) -> None:
    owner.use(read_tool(f"{WORKING_FOLDER}/src/webhooks/retry.py"), branch="webhook-retries")
    collide(owner, dana)

    refused = reason_in(dana.edit(FILE))

    assert "branch webhook-retries" in refused and "src/webhooks/retry.py" in refused


def test_a_session_in_a_coding_agent_with_hooks_is_never_told_it_has_none_before_its_first_hook(
    owner: Session, dana: Session
) -> None:
    in_claude_code = dana.as_agent("claude-code").as_session("claude-code-first-tool")
    state(owner, WEBHOOKS)

    stated = notices_of(in_claude_code.call("set_activity", activity=RETRIES, session=in_claude_code.identifier))

    assert GATED not in stated, "its hook before the edit refuses it, so it is not told to hold the gate itself"
