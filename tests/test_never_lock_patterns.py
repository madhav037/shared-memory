"""A project's own never-lock patterns: its leads and the team's admins add and remove them from a session, every
member of the project reads them, and a file matching one never locks in any of the project's repositories."""

from __future__ import annotations

import dataclasses

import pytest

from shared_memory.locks import NEVER_LOCK, PATTERN_LIMIT, Locks
from tests.support import (
    Console,
    ConsoleClient,
    RunningServer,
    Session,
    Team,
    add,
    added_context,
    create,
    member,
    signed_in_owner,
)
from tests.test_locks import refused, take
from tests.test_restricted_projects import restricted

SNAPSHOT = "tests/snapshots/invoice.snap"


def payments(team: Team, dana: Session) -> tuple[Session, Session, Session]:
    """A project Dana created, so she leads it, with Cole working in it and the team's owner, an admin who doesn't
    lead it."""
    project = dana.call("create_project", name="Payments")["project_id"]
    cole = member(team, project, "emp-3", "Cole Coder").in_project(project, "payments-api")
    return dana.in_project(project, "payments-api"), cole, team.owner().in_project(project, "payments-api")


def patterns(session: Session) -> list[str]:
    """The project's own never-lock patterns, as the tool lists them."""
    return [one["pattern"] for one in session.call("never_lock")["project"]]


# Adding and removing


def test_a_lead_adds_a_pattern_and_a_matching_file_never_locks_in_any_of_the_projects_repositories(
    team: Team, dana: Session
) -> None:
    lead, cole, _ = payments(team, dana)
    before = take(cole, "tests/snapshots/before.snap")

    added = lead.call("never_lock", add="*.snap")
    here = take(cole, SNAPSHOT)
    there = take(lead, SNAPSHOT, repository="payments-web")

    assert before["locked"] is True
    assert added["added"] == "*.snap"
    assert [one["pattern"] for one in added["project"]] == ["*.snap"]
    for answer, repository in ((here, "payments-api"), (there, "payments-web")):
        assert (answer["locked"], answer["repository"], answer["never_locks"]) == (False, repository, "*.snap")
        assert "never locks" in answer["message"]


def test_a_pattern_with_a_slash_is_matched_from_the_repositorys_root(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)

    lead.call("never_lock", add="src\\generated\\**")

    assert patterns(cole) == ["src/generated/**"], "kept with forward slashes, as a path is"
    assert take(cole, "src/generated/api/client.py")["never_locks"] == "src/generated/**"
    assert take(cole, "web/src/generated/client.py")["locked"] is True


def test_removing_the_pattern_makes_the_file_lock_again(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)
    lead.call("never_lock", add="*.snap")

    removed = lead.call("never_lock", remove="*.snap")

    assert removed["removed"] == "*.snap"
    assert removed["project"] == []
    assert take(cole, SNAPSHOT)["locked"] is True
    assert "Cole Coder" in refused(lead, SNAPSHOT)


def test_an_admin_who_does_not_lead_the_project_adds_and_removes(team: Team, dana: Session) -> None:
    _, cole, admin = payments(team, dana)

    admin.call("never_lock", add="*.snap")
    while_added = take(cole, SNAPSHOT)
    admin.call("never_lock", remove="*.snap")

    assert while_added["locked"] is False
    assert take(cole, SNAPSHOT)["locked"] is True


def test_a_member_who_neither_leads_the_project_nor_administers_is_refused_and_told_who_can(
    team: Team, dana: Session
) -> None:
    lead, cole, _ = payments(team, dana)
    lead.call("never_lock", add="*.snap")

    adding = cole.refusal("never_lock", add="*.fixture")
    removing = cole.refusal("never_lock", remove="*.snap")

    for refusal in (adding, removing):
        assert "Only this project's leads and the team's admins" in refusal
    assert patterns(cole) == ["*.snap"]
    assert take(cole, "tests/invoice.fixture")["locked"] is True


# Reading


def test_any_member_of_the_project_reads_the_built_in_list_and_the_projects_patterns(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)
    lead.call("never_lock", add="*.snap")
    team.server.clock.advance(minutes=1)
    lead.call("never_lock", add="docs/api/**")

    listed = cole.call("never_lock")

    assert listed["built_in"] == list(NEVER_LOCK)
    assert [(one["pattern"], one["added_by"]) for one in listed["project"]] == [
        ("*.snap", "emp-2"),
        ("docs/api/**", "emp-2"),
    ]
    assert all(one["added_at"] for one in listed["project"])


def test_another_projects_patterns_do_not_apply(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)

    lead.call("never_lock", add="*.snap")

    assert patterns(dana) == [], "Billing, the project Dana works in but doesn't lead, has none"
    assert take(dana, SNAPSHOT)["locked"] is True
    assert take(cole, SNAPSHOT)["locked"] is False


def test_a_pattern_added_through_one_worker_holds_for_a_session_calling_through_another(
    team: Team, dana: Session, second_server: RunningServer
) -> None:
    lead, cole, _ = payments(team, dana)

    lead.call("never_lock", add="*.snap")

    assert take(dataclasses.replace(cole, server=second_server), SNAPSHOT)["locked"] is False


# What is refused


@pytest.mark.parametrize(
    "pattern",
    ["", "   ", "*", "**", "**/*", "*.*", "/src/generated/**", "../other/**", "src/../**", "docs/", "x" * (PATTERN_LIMIT + 1)],
)
def test_a_pattern_that_is_not_a_usable_glob_is_refused(team: Team, dana: Session, pattern: str) -> None:
    lead, _, _ = payments(team, dana)

    refusal = lead.refusal("never_lock", add=pattern)

    assert "isn't a usable never-lock pattern" in refusal
    assert patterns(lead) == []


@pytest.mark.parametrize("pattern", ["*.[ch]", "src/{a,b}/**", "!keep.snap"])
def test_a_glob_the_server_does_not_read_is_refused_and_told_what_it_reads(
    team: Team, dana: Session, pattern: str
) -> None:
    lead, _, _ = payments(team, dana)

    refusal = lead.refusal("never_lock", add=pattern)

    assert "isn't a usable never-lock pattern" in refusal
    assert "`*`, `?` and `**`" in refusal


def test_adding_a_pattern_twice_or_one_that_is_built_in_is_refused(team: Team, dana: Session) -> None:
    lead, _, _ = payments(team, dana)
    lead.call("never_lock", add="*.snap")

    again = lead.refusal("never_lock", add=" *.snap ")
    built_in = lead.refusal("never_lock", add="yarn.lock")

    assert "already" in again
    assert "built in" in built_in
    assert patterns(lead) == ["*.snap"]


def test_the_built_in_list_cannot_be_removed_and_neither_can_a_pattern_the_project_does_not_have(
    team: Team, dana: Session
) -> None:
    lead, cole, _ = payments(team, dana)

    built_in = lead.refusal("never_lock", remove="yarn.lock")
    unknown = lead.refusal("never_lock", remove="*.snap")

    assert "built in" in built_in and "can't be removed" in built_in
    assert "isn't one of this project's never-lock patterns" in unknown
    assert take(cole, "web/yarn.lock")["locked"] is False


def test_adding_and_removing_in_one_call_is_refused(team: Team, dana: Session) -> None:
    lead, _, _ = payments(team, dana)

    refusal = lead.refusal("never_lock", add="*.snap", remove="*.fixture")

    assert "one at a time" in refusal
    assert patterns(lead) == []


def test_a_session_connected_to_no_project_is_refused(team: Team) -> None:
    assert "isn't connected to a project" in team.owner().refusal("never_lock")


def test_a_member_outside_a_restricted_project_cannot_read_its_patterns(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-never-lock", 2601)
    it.owner.in_project(it.billing, "billing-api").call("never_lock", add="*.snap")

    refusal = it.dana.in_project(it.billing, "billing-api").refusal("never_lock")

    assert "is restricted" in refusal
    assert "*.snap" not in refusal


# A lock already held


def test_a_lock_already_held_on_a_file_that_now_matches_a_pattern_no_longer_blocks_anyone(
    team: Team, dana: Session
) -> None:
    lead, cole, _ = payments(team, dana)
    locks: Locks = team.server.app.state.locks
    assert lead.project is not None
    take(cole, SNAPSHOT)
    take(cole, "src/invoices.py")
    while_held = refused(lead, SNAPSHOT)

    lead.call("never_lock", add="*.snap")

    assert "Cole Coder" in while_held
    assert take(lead, SNAPSHOT)["locked"] is False
    assert take(cole, SNAPSHOT)["locked"] is False
    assert [lock.path for lock in locks.held(lead.project)] == ["src/invoices.py"], "the lock on the snapshot ended"
    assert locks.never_locks(lead.project, SNAPSHOT) == "*.snap"

    lead.call("never_lock", remove="*.snap")

    assert take(lead, SNAPSHOT)["locked"] is True, "the lock that ended does not come back to its old holder"


def test_the_holder_of_a_lock_an_added_pattern_ended_is_told_once_on_its_next_prompt(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)
    lead.start()
    take(cole, SNAPSHOT)
    take(cole, "src/invoices.py")

    lead.call("never_lock", add="*.snap")
    told = added_context(cole.prompt("write a haiku about cats"))

    assert f"payments-api:{SNAPSHOT}" in told
    assert "no longer holds the lock" in told
    assert "'*.snap'" in told and "Dana Dev (emp-2)" in told, "why, and who added the pattern"
    assert "src/invoices.py" not in told, "a lock the pattern doesn't match is still held"
    assert cole.prompt("write a haiku about cats") == {}
    assert lead.prompt("write a haiku about cats") == {}, "a session that held no such lock is told nothing"


def test_a_holder_with_no_prompt_hook_is_told_in_the_result_of_its_next_tool_call(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)
    take(cole, SNAPSHOT)
    take(cole.as_session("second-session"), "tests/snapshots/refund.snap")

    lead.call("never_lock", add="*.snap")
    next_take = take(cole, "src/invoices.py")

    assert len(next_take["notices"]) == 1
    assert f"payments-api:{SNAPSHOT}" in next_take["notices"][0]
    assert take(cole, "src/invoices.py")["notices"] == []
    assert SNAPSHOT not in added_context(cole.prompt("write a haiku about cats")), "told once, wherever it was told"
    assert "refund.snap" in added_context(cole.as_session("second-session").prompt("write a haiku about cats"))


def test_a_holder_whose_session_ended_is_not_told_when_it_starts_again(team: Team, dana: Session) -> None:
    lead, cole, _ = payments(team, dana)
    take(cole, SNAPSHOT)
    lead.call("never_lock", add="*.snap")

    cole.end()
    cole.start()

    assert SNAPSHOT not in added_context(cole.prompt("write a haiku about cats"))


# The audit log


def test_each_add_and_remove_is_in_the_audit_log_with_who_made_it(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-never-lock-audit", 2602)
    billing = create(signed_out, "Billing")["project_id"]
    lead = Session(console.server, add(signed_out, "emp-3", "Lena Lead")["personal_token"])
    checkout = lead.call("create_project", name="Checkout")["project_id"]

    lead.in_project(checkout, "checkout-api").call("never_lock", add="*.snap")
    owner.in_project(checkout, "checkout-api").as_agent("claude-code").call("never_lock", remove="*.snap")
    owner.in_project(billing, "billing-api").call("never_lock", add="*.fixture")

    response = signed_out.get(f"/api/audit?project={checkout}")
    assert response.status_code == 200, response.text
    events = [event for event in response.json()["events"] if event["kind"].startswith("never_lock_pattern_")]
    assert [(event["kind"], event["actor"], event["target"]) for event in events] == [
        ("never_lock_pattern_removed", "E1001", "*.snap"),
        ("never_lock_pattern_added", "emp-3", "*.snap"),
    ]
    assert events[0]["detail"] == {"agent": "Claude Code"}
