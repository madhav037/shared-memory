"""A session's told record (#565, spec #504): its briefing as delivered and each recall, in order, with when and the
memory repository's head commit, never what its member typed. Its own member, the project's leads and the team's admins
read it through the console's JSON API; records older than `told_days` are pruned.

Sessions are driven over HTTP through the session driver; the record is read through the console's JSON API."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import psycopg
import pytest

from shared_memory.config import Settings
from shared_memory.console_contract import DECLARATIONS
from tests.support import (
    Console,
    ConsoleClient,
    Session,
    add,
    ask,
    promote_keeping_both,
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
TOLD = "/projects/{project_id}/sessions/{session_number}/told"


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session]:
    """The owner signed in to the console, with a project of theirs holding the pnpm memory, and a session in it."""
    owner = signed_in_owner(console, client, github, account)
    project: str = owner.call("create_project", name="Billing")["project_id"]
    return project, owner.in_project(project, "billing-api")


def number_of(client: ConsoleClient, project: str, member_id: str) -> int:
    """The session number of the member's active session in the project, as the Sessions page gives it."""
    [found] = [one for one in ask(client, f"/api/projects/{project}/sessions")["sessions"] if one["member_id"] == member_id]
    number: int = found["session_number"]
    return number


def told_url(project: str, number: int) -> str:
    return f"/api/projects/{project}/sessions/{number}/told"


def told(client: ConsoleClient, project: str, number: int) -> dict[str, Any]:
    return ask(client, told_url(project, number))


def test_a_sessions_briefing_and_each_recall_are_recorded_in_order_with_when_and_the_head_commit(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-told-order", 5651)
    pnpm = promote_keeping_both(in_project, PNPM)
    session = in_project.as_session("olive-told")
    started = session.start()
    console.clock.advance(minutes=2)
    session.prompt(PROMPT)
    number = number_of(signed_out, project, "E1001")

    found = told(signed_out, project, number)

    assert (found["project_id"], found["session_number"]) == (project, number)
    assert (found["member_id"], found["member_name"]) == ("E1001", "Olive Owner")
    assert found["told_days"] == 30
    briefing, recall = found["told"]
    assert briefing["kind"] == "briefing"
    assert briefing["briefing"] == started["hookSpecificOutput"]["additionalContext"]
    assert "`olive-told`" in briefing["briefing"]
    assert briefing["memory"] is None
    assert recall["kind"] == "recall"
    assert recall["briefing"] is None
    assert recall["memory"]["path"] == pnpm
    assert recall["memory"]["title"] == PNPM["title"]
    elapsed = datetime.fromisoformat(recall["at"]) - datetime.fromisoformat(briefing["at"])
    assert elapsed.total_seconds() == 120, "each comes with when it was told"
    assert re.fullmatch(r"[0-9a-f]{40}", recall["commit"])
    assert briefing["commit"] == recall["commit"], "nothing was saved between the two"
    # The memory as the session was told it, at the head commit the record keeps.
    then = ask(signed_out, "/api/memory/version", path=pnpm, commit=recall["commit"])
    assert "We use pnpm for every package." in then["text"]


def test_the_told_record_never_holds_what_the_member_typed(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-told-prompt", 5652)
    promote_keeping_both(in_project, PNPM)
    session = in_project.as_session("olive-typed")
    session.start()
    session.prompt(PROMPT)
    number = number_of(signed_out, project, "E1001")

    found = told(signed_out, project, number)

    assert [one["kind"] for one in found["told"]] == ["briefing", "recall"]
    assert "which package manager" not in json.dumps(found)
    with psycopg.connect(console.server.settings.database_url) as conn:
        kept = conn.execute("SELECT * FROM session_told").fetchall()
    assert "which package manager" not in repr(kept)


def test_the_briefing_tool_and_a_prompt_that_recalls_nothing_new(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-told-tool", 5653)
    promote_keeping_both(in_project, PNPM)
    session = in_project.as_session("olive-tool")
    fetched = session.call("briefing", session=session.identifier)
    session.prompt(PROMPT)
    # Told once: the same prompt again adds nothing to the session, and so nothing to its record.
    session.prompt(PROMPT)
    number = number_of(signed_out, project, "E1001")

    found = told(signed_out, project, number)

    assert [one["kind"] for one in found["told"]] == ["briefing", "recall"]
    assert found["told"][0]["briefing"] == fetched


def test_its_member_the_projects_leads_and_the_teams_admins_read_it_and_no_one_else(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, _ = a_project(console, signed_out, "olive-told-readers", 5654)
    dana_token = add(signed_out, "emp-2", "Dana Dev", github="dana-told-readers")["personal_token"]
    add(signed_out, "emp-3", "Lee Lead", github="lee-told-readers")
    add(signed_out, "emp-4", "Ada Admin", github="ada-told-readers")
    add(signed_out, "emp-5", "Ash Dev", github="ash-told-readers")
    assert signed_out.post_json(f"/api/projects/{project}/leads", {"member_id": "emp-3"}).status_code == 200
    assert signed_out.post_json("/api/members/emp-4/admin", {"admin": True}).status_code == 200
    Session(console.server, dana_token).in_project(project, "billing-api").as_session("dana-told").start()
    number = number_of(signed_out, project, "emp-2")

    dana = signed_in(console, "dana-told-readers", 5655)
    lead = signed_in(console, "lee-told-readers", 5656)
    admin = signed_in(console, "ada-told-readers", 5657)
    ash = signed_in(console, "ash-told-readers", 5658)

    for reader in (dana, lead, admin, signed_out):
        assert [one["kind"] for one in told(reader, project, number)["told"]] == ["briefing"]
    refused = ash.get(told_url(project, number))
    assert refused.status_code == 403
    assert refused.json()["message"] == (
        "Only a session's own member, its project's leads and the team's admins can read what it was told."
    )
    # The Sessions page says who may open it.
    mine = {one["member_id"]: one["you_may_read_told"] for one in ask(dana, f"/api/projects/{project}/sessions")["sessions"]}
    theirs = {one["member_id"]: one["you_may_read_told"] for one in ask(ash, f"/api/projects/{project}/sessions")["sessions"]}
    assert mine == {"emp-2": True}
    assert theirs == {"emp-2": False}
    assert ask(lead, f"/api/projects/{project}/sessions")["sessions"][0]["you_may_read_told"] is True


def test_a_session_of_another_project_or_none_at_all_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-told-elsewhere", 5659)
    other = in_project.call("create_project", name="Payments")["project_id"]
    in_project.as_session("olive-billing").start()
    number = number_of(signed_out, project, "E1001")

    elsewhere = signed_out.get(told_url(other, number))
    nowhere = signed_out.get(told_url(project, 987654321))
    not_a_number = signed_out.get(f"/api/projects/{project}/sessions/first/told")

    assert elsewhere.status_code == 403
    assert nowhere.status_code == 403
    assert not_a_number.status_code == 422


def test_a_session_that_ended_keeps_its_told_record(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-told-ended", 5660)
    session = in_project.as_session("olive-ending")
    session.start()
    number = number_of(signed_out, project, "E1001")
    session.end()

    assert [one["kind"] for one in told(signed_out, project, number)["told"]] == ["briefing"]


def test_records_past_told_days_are_pruned(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-told-pruned", 5661)
    session = in_project.as_session("olive-pruned")
    session.start()
    number = number_of(signed_out, project, "E1001")
    console.clock.advance(days=31)
    session.start()
    console.github.as_(5661, "olive-told-pruned")
    signed_out.sign_in()

    found = told(signed_out, project, number)

    assert len(found["told"]) == 1, "the first briefing is past 30 days"
    with psycopg.connect(console.server.settings.database_url) as conn:
        oldest = conn.execute("SELECT min(at) AS oldest FROM session_told").fetchone()
    assert oldest is not None
    assert (console.clock() - oldest[0]).days < 30, "and it is gone from the server, not only from the page"


def test_reading_a_told_record_changes_nothing(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, in_project = a_project(console, signed_out, "olive-told-unchanged", 5662)
    promote_keeping_both(in_project, PNPM)
    session = in_project.as_session("olive-unchanged")
    session.start()
    session.prompt(PROMPT)
    number = number_of(signed_out, project, "E1001")
    reached = watch_for_writes(monkeypatch)

    first = told(signed_out, project, number)
    again = told(signed_out, project, number)

    [declared] = [one for one in DECLARATIONS if one.path == TOLD]
    assert (declared.method, declared.changes) == ("GET", False)
    assert reached == []
    assert first == again


def test_told_days_is_a_setting() -> None:
    assert Settings.from_env({}).told_days == 30
    assert Settings.from_env({"SHARED_MEMORY_TOLD_DAYS": "7"}).told_days == 7
