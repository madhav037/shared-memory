"""A member's recent sessions (#566, spec #504): each session of the project from the last `told_days`, the most
recently seen first, with its last stated activity, its branch, when it ran and how many memories it was told, for
the same readers as its told record: its own member, the project's leads and the team's admins. An ended session keeps
its last stated activity.

Sessions are driven over HTTP through the session driver; the list is read through the console's JSON API."""

from __future__ import annotations

from typing import Any

import pytest

from shared_memory.console_contract import DECLARATIONS
from tests.support import (
    WORKING_FOLDER,
    Console,
    ConsoleClient,
    Session,
    add,
    ask,
    promote_keeping_both,
    read_tool,
    signed_in,
    signed_in_owner,
)
from tests.test_console_never_writes_memory import watch_for_writes

PNPM = {
    "title": "Use pnpm, not npm",
    "summary": "Every package in billing is managed with pnpm, never npm.",
    "type": "convention",
    "body": "We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
}
PROMPT = "which package manager do we use for the billing packages?"
RECENT = "/projects/{project_id}/sessions/recent"


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session]:
    """The owner signed in to the console, with a project of theirs and a coding agent in it."""
    owner = signed_in_owner(console, client, github, account)
    project: str = owner.call("create_project", name="Billing")["project_id"]
    return project, owner.in_project(project, "billing-api")


def recent(client: ConsoleClient, project: str) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/sessions/recent")


def test_an_ended_session_keeps_its_last_stated_activity(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-recent-ended", 5671)
    session = in_project.as_session("olive-docs")
    session.start()
    session.call("set_activity", activity="Drafting the retry docs", session=session.identifier)
    session.call("set_activity", activity="Writing the webhook retry docs", session=session.identifier)
    session.use(read_tool(f"{WORKING_FOLDER}/docs/webhooks.md"), branch="docs/webhook-retries")
    console.clock.advance(minutes=5)
    session.end()

    [ended] = recent(signed_out, project)["sessions"]

    assert ended["activity"] == "Writing the webhook retry docs", "its last stated activity, kept past its end"
    assert ended["branch"] == "docs/webhook-retries"
    assert ended["active"] is False
    assert ask(signed_out, f"/api/projects/{project}/sessions")["sessions"] == [], "it is no longer active"
    # Started again, it is active without the activity it stated before it ended.
    session.start()
    [again] = recent(signed_out, project)["sessions"]
    assert again["active"] is True
    assert again["activity"] is None


def test_each_recent_session_comes_with_when_it_ran_and_how_many_memories_it_was_told(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-recent-told", 5672)
    promote_keeping_both(in_project, PNPM)
    # Each names its coding agent in a tool call: a hook of no agent family names none.
    earlier = in_project.as_agent("claude-code").as_session("olive-earlier")
    earlier.start()
    earlier.call("set_activity", activity="Choosing the package manager", session=earlier.identifier)
    earlier.prompt(PROMPT)
    earlier.end()
    console.clock.advance(minutes=10)
    later = in_project.as_agent("codex").as_session("olive-later")
    later.start()
    later.call("set_activity", activity="Splitting invoices", session=later.identifier)

    found = recent(signed_out, project)

    assert (found["project_id"], found["project_name"], found["told_days"]) == (project, "Billing", 30)
    newest, oldest = found["sessions"]
    assert (newest["agent"], newest["active"], newest["memories_told"]) == ("codex", True, 0)
    assert (oldest["agent"], oldest["active"], oldest["memories_told"]) == ("claude-code", False, 1)
    assert oldest["activity"] == "Choosing the package manager", "an ended session keeps its agent and activity"
    assert oldest["member_id"] == "E1001"
    assert oldest["member_name"] == "Olive Owner"
    assert oldest["repository"] == "billing-api"
    assert oldest["started_at"] < newest["started_at"]
    assert oldest["last_seen_at"] >= oldest["started_at"]
    # Each opens its told record by its number.
    told = ask(signed_out, f"/api/projects/{project}/sessions/{oldest['session_number']}/told")
    assert [one["kind"] for one in told["told"]] == ["briefing", "recall"]


def test_a_member_sees_their_own_and_the_projects_leads_and_the_teams_admins_see_every_one(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-recent-readers", 5673)
    dana_token = add(signed_out, "emp-2", "Dana Dev", github="dana-recent-readers")["personal_token"]
    ash_token = add(signed_out, "emp-5", "Ash Dev", github="ash-recent-readers")["personal_token"]
    add(signed_out, "emp-3", "Lee Lead", github="lee-recent-readers")
    add(signed_out, "emp-4", "Ada Admin", github="ada-recent-readers")
    assert signed_out.post_json(f"/api/projects/{project}/leads", {"member_id": "emp-3"}).status_code == 200
    assert signed_out.post_json("/api/members/emp-4/admin", {"admin": True}).status_code == 200
    in_project.as_session("olive-own").start()
    Session(console.server, dana_token).in_project(project, "billing-api").as_session("dana-own").start()
    Session(console.server, ash_token).in_project(project, "billing-api").as_session("ash-own").start()

    dana = signed_in(console, "dana-recent-readers", 5674)
    lead = signed_in(console, "lee-recent-readers", 5675)
    admin = signed_in(console, "ada-recent-readers", 5676)

    def whose(client: ConsoleClient) -> set[str]:
        return {one["member_id"] for one in recent(client, project)["sessions"]}

    assert whose(dana) == {"emp-2"}
    assert whose(lead) == {"E1001", "emp-2", "emp-5"}
    assert whose(admin) == {"E1001", "emp-2", "emp-5"}
    assert whose(signed_out) == {"E1001", "emp-2", "emp-5"}


def test_a_session_last_seen_more_than_told_days_ago_is_not_listed(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-recent-old", 5677)
    old = in_project.as_session("olive-old")
    old.start()
    old.end()
    console.clock.advance(days=31)
    in_project.as_session("olive-new").start()
    console.github.as_(5677, "olive-recent-old")
    signed_out.sign_in()

    found = recent(signed_out, project)["sessions"]

    assert [one["active"] for one in found] == [True]


def test_reading_recent_sessions_changes_nothing(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, in_project = a_project(console, signed_out, "olive-recent-unchanged", 5678)
    session = in_project.as_session("olive-unchanged")
    session.start()
    session.call("set_activity", activity="Splitting invoices", session=session.identifier)
    session.end()
    reached = watch_for_writes(monkeypatch)

    first = recent(signed_out, project)
    again = recent(signed_out, project)

    [declared] = [one for one in DECLARATIONS if one.path == RECENT]
    assert (declared.method, declared.changes) == ("GET", False)
    assert reached == []
    assert first == again
