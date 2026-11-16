"""The gate (ADR-0024): a later session's file edits are refused until the project's wait passes or its member says it
is different work. Reading still goes ahead, a member's own sessions never gate each other, and a gate ends with its
earlier session.

The collisions here are made as `test_collisions.py` makes them: Olive's session states an activity, and Dana's first
prompt scores 0.8 against it, so Dana's is the later session."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import (
    REPO_ROOT,
    WORKING_FOLDER,
    RunningServer,
    Session,
    Team,
    TestClock,
    added_context,
    fresh_database,
    member,
    search_tool,
)
from tests.test_before_edit import ALLOWED, reason_in
from tests.test_collisions import PROMPT, PROMPT_BELOW, WEBHOOKS, ChosenSimilarity, state, warnings
from tests.test_locks import FILE

GATED = "[gated]"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    """This module's own server, in place of the one every other module shares, for the chosen embeddings."""
    settings = Settings(
        database_url=fresh_database("shared_memory_gates"),
        memory_root=tmp_path_factory.mktemp("gates-memory"),
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
    first_line = reason.splitlines()[0]
    assert first_line.startswith(GATED)
    assert "different work" in first_line and "different_work" in first_line
    assert "Olive Owner" in reason
    assert "Claude Code" in reason
    assert f'"{WEBHOOKS}"' in reason
    assert "5 minutes left" in reason
    assert "ask your member" in reason


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


def answer_gate(session: Session, gate: str, answer: str, text: str | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {"session": session.identifier, "gate": gate, "answer": answer}
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
    assert reason.startswith(GATED) and "refused" in reason


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

    refused = owner.refusal("answer_gate", session=owner.identifier, gate="emp-2", answer="refuse")

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

    assert still.startswith(GATED) and "Cole Coder" in still and "Olive Owner" not in still
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

    assert reason.startswith(GATED) and "Cole Coder" in reason and "refused" in reason
    assert "Olive Owner" not in reason


def test_only_the_earlier_sessions_own_member_can_answer(owner: Session, dana: Session, cole: Session) -> None:
    collide(owner, dana)

    by_another = cole.refusal("answer_gate", session=owner.identifier, gate="emp-2", answer="agree")
    by_the_later = dana.refusal("answer_gate", session=dana.identifier, gate="emp-2", answer="agree")

    assert "No gate" in by_another and "No gate" in by_the_later
    assert GATED in reason_in(dana.edit(FILE)), "still gated"


def test_an_answer_after_the_wait_has_passed_is_refused(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=5)

    refused = owner.refusal("answer_gate", session=owner.identifier, gate="emp-2", answer="refuse")

    assert "wait" in refused
    assert dana.edit(FILE) == ALLOWED


def test_an_answer_other_than_agree_or_refuse_is_refused(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    refused = owner.refusal("answer_gate", session=owner.identifier, gate="emp-2", answer="maybe")

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

    assert owner.edit("src/other.py") == ALLOWED, "its member answered"


def test_an_answer_to_the_gate_answers_the_urgent_message_too(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    answer_gate(owner, "emp-2", "agree")

    assert owner.edit("src/other.py") == ALLOWED


def test_without_an_answer_the_wait_lifts_an_urgent_messages_gate(team: Team, owner: Session, dana: Session) -> None:
    collide(owner, dana)
    team.server.clock.advance(minutes=2)
    send_urgent(dana, "owner-1")
    team.server.clock.advance(minutes=4, seconds=59)
    assert GATED in reason_in(owner.edit("src/other.py")), "the wait runs from the urgent message"

    team.server.clock.advance(seconds=1)

    assert owner.edit("src/other.py") == ALLOWED


def test_different_work_lifts_an_urgent_messages_gate(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    lifted = different_work(owner)

    assert lifted["lifted"] == ["Dana Dev"]
    assert owner.edit("src/other.py") == ALLOWED


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
    assert owner.edit("src/other.py") == ALLOWED
    assert URGENT not in heard(owner), "nothing was sent"


def test_only_the_later_session_sends_an_urgent_message(owner: Session, dana: Session) -> None:
    collide(owner, dana)

    refused = refused_urgent(owner, "emp-2")

    assert "later" in refused
    assert owner.edit("src/other.py") == ALLOWED


def test_an_urgent_messages_gate_ends_when_its_later_session_ends(owner: Session, dana: Session) -> None:
    collide(owner, dana)
    send_urgent(dana, "owner-1")

    dana.end()

    assert owner.edit("src/other.py") == ALLOWED


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
