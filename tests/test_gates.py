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

    assert owner.edit("src/other.py") == ALLOWED


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
        ("different_work", "emp-2", {"earlier": "E1001", "score": 0.8, "cause": "prompt"}),
        ("gate_timed_out", "emp-3", {"earlier": "E1001", "score": 0.8, "cause": "prompt"}),
    ], "each recorded once"
    assert PROMPT not in str(entries)


def test_a_change_to_the_wait_is_in_the_audit_log(team: Team, dana: Session) -> None:
    lead, _, _ = payments(team, dana)

    lead.call("project_wait", minutes=12)

    assert gate_entries(team.server, lead.project or "") == [("project_wait_changed", "emp-2", {"minutes": 12})]
