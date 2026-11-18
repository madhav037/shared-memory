"""Project health (#553, #572, spec #504): a read-only page for a project's leads and the team's admins, listing the
project's possibly outdated memory, its memory in doubt and its coverage gaps. Driven through the console's JSON API.

Nothing on it changes anything (ADR-0009): pinning, unpinning, deciding and retiring stay on their own screens."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

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
from tests.test_tied_files import promoted, remember

TAX = {
    "title": "Sales tax is fifteen percent",
    "summary": "Invoices add fifteen percent sales tax.",
    "type": "convention",
    "body": "Every invoice adds a flat fifteen percent sales tax on the subtotal.",
}
RETRIES = {
    "title": "Webhooks retry three times",
    "summary": "A failed webhook is retried three times with backoff.",
    "type": "gotcha",
    "body": "The provider retries a failed webhook three times, an hour apart, before it gives up.",
}
EXPORTS = {
    "title": "Exports are written as CSV",
    "summary": "Every ledger export is a CSV file.",
    "type": "decision",
    "body": "Ledger exports are CSV with a header row, never spreadsheets, so finance can diff them.",
}
TAX_LINE = {"code_reference": "billing-api:src/tax.py:42", "quoted_line": "RATE = Decimal('0.20')"}


def health(client: ConsoleClient, project: str) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/health")


def paths(listed: list[dict[str, Any]]) -> list[str]:
    return [one["path"] for one in listed]


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session]:
    """The owner signed in to the console, with a project of theirs and a session in it."""
    owner = signed_in_owner(console, client, github, account)
    project: str = owner.call("create_project", name="Billing")["project_id"]
    return project, owner.in_project(project, "billing-api")


def member_in(console: Console, client: ConsoleClient, project: str, member_id: str, name: str) -> Session:
    """A member added through the console, with a session in the project."""
    return Session(console.server, add(client, member_id, name)["personal_token"]).in_project(project, "billing-api")


def sign_in_again(console: Console, client: ConsoleClient, github: str, account: int) -> None:
    """The console's sign-in lapses while the clock moves on by months."""
    console.github.as_(account, github)
    client.sign_in()


def test_project_health_lists_memory_unused_past_outdated_after_days(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-outdated", 5531)
    unused = promote_keeping_both(in_project, TAX)
    read_lately = promote_keeping_both(in_project, RETRIES)
    console.clock.advance(days=30)
    saved_lately = promote_keeping_both(in_project, EXPORTS)
    console.clock.advance(days=29)
    in_project.call("read", path=read_lately)
    console.clock.advance(days=2)
    sign_in_again(console, signed_out, "olive-health-outdated", 5531)

    found = health(signed_out, project)

    assert found["project_id"] == project
    assert found["project_name"] == "Billing"
    assert found["outdated_after_days"] == 60
    assert paths(found["possibly_outdated"]) == [unused]
    [listed] = found["possibly_outdated"]
    assert listed["title"] == TAX["title"]
    assert listed["last_used"] is not None
    assert read_lately not in paths(found["possibly_outdated"])
    assert saved_lately not in paths(found["possibly_outdated"])


def test_project_health_leaves_out_pinned_memory(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-pinned", 5532)
    pinned = promote_keeping_both(in_project, TAX)
    unpinned = promote_keeping_both(in_project, RETRIES)
    in_topic = promote_keeping_both(in_project, {**EXPORTS, "type": "gotcha", "topic": "ledger"})
    assert signed_out.post_json("/api/memory/pin", {"path": pinned}).status_code == 200
    assert signed_out.post_json("/api/memory/pin", {"path": in_topic.rsplit("/", 1)[0]}).status_code == 200
    console.clock.advance(days=90)
    sign_in_again(console, signed_out, "olive-health-pinned", 5532)

    found = health(signed_out, project)

    assert paths(found["possibly_outdated"]) == [unpinned]


def test_project_health_lists_memory_in_doubt_with_count_and_reasons_most_doubted_first(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-doubts", 5533)
    once = promote_keeping_both(in_project, TAX)
    twice = promote_keeping_both(in_project, RETRIES)
    asked_to_retire = promote_keeping_both(in_project, EXPORTS)
    sound = promote_keeping_both(in_project, {**EXPORTS, "title": "Ledgers close monthly", "summary": "Monthly."})
    dana = member_in(console, signed_out, project, "emp-2", "Dana Dev")
    ash = member_in(console, signed_out, project, "emp-3", "Ash Dev")
    dana.call("challenge", path=once, reason="misled", reasoning="Invoices came out wrong.")
    dana.call("challenge", path=twice, reason="misled")
    ash.call("challenge", path=twice, reason="contradicts_code", **TAX_LINE)
    # A challenge that names no reason doesn't put a memory in doubt.
    dana.call("retire", path=asked_to_retire)

    found = health(signed_out, project)

    assert paths(found["in_doubt"]) == [twice, once]
    first, second = found["in_doubt"]
    assert first["title"] == RETRIES["title"]
    assert first["in_doubt"] == {
        "count": 2,
        "reasons": [
            {"reason": "misled", "count": 1, "code_references": []},
            {"reason": "contradicts_code", "count": 1, "code_references": ["billing-api:src/tax.py:42"]},
        ],
        "line": "In doubt: 1 says it misled them; 1 says it contradicts billing-api:src/tax.py:42",
    }
    assert second["in_doubt"]["count"] == 1
    assert [one["reason"] for one in second["in_doubt"]["reasons"]] == ["misled"]
    assert sound not in paths(found["in_doubt"])


def test_project_health_is_readable_by_a_lead_and_an_admin(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-readers", 5534)
    path = promote_keeping_both(in_project, TAX)
    member_in(console, signed_out, project, "emp-2", "Dana Dev").call("challenge", path=path, reason="misled")
    add(signed_out, "emp-3", "Lee Lead", github="lee-health-readers")
    add(signed_out, "emp-4", "Ada Admin", github="ada-health-readers")
    assert signed_out.post_json(f"/api/projects/{project}/leads", {"member_id": "emp-3"}).status_code == 200
    assert signed_out.post_json("/api/members/emp-4/admin", {"admin": True}).status_code == 200

    lead = signed_in(console, "lee-health-readers", 5535)
    admin = signed_in(console, "ada-health-readers", 5536)

    assert paths(health(lead, project)["in_doubt"]) == [path]
    assert paths(health(admin, project)["in_doubt"]) == [path]


def test_project_health_is_refused_to_a_member_who_is_not_a_lead(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_project(console, signed_out, "olive-health-refused", 5537)
    add(signed_out, "emp-2", "Dana Dev", github="dana-health-refused")
    dana = signed_in(console, "dana-health-refused", 5538)

    refused = dana.get(f"/api/projects/{project}/health")

    assert refused.status_code == 403
    assert refused.json()["message"] == "Only this project's leads and the team's admins can see its health."


def test_project_health_of_a_restricted_project_is_refused_outside_its_leads_and_admins(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, _ = a_project(console, signed_out, "olive-health-restricted", 5539)
    add(signed_out, "emp-2", "Dana Dev", github="dana-health-restricted")
    add(signed_out, "emp-3", "Ash Dev", github="ash-health-restricted")
    add(signed_out, "emp-4", "Lee Lead", github="lee-health-restricted")
    add(signed_out, "emp-5", "Ada Admin", github="ada-health-restricted")
    assert signed_out.post_json(f"/api/projects/{project}/restrict", {"restricted": True}).status_code == 200
    assert signed_out.post_json(f"/api/projects/{project}/access", {"member_id": "emp-2"}).status_code == 200
    assert signed_out.post_json(f"/api/projects/{project}/leads", {"member_id": "emp-4"}).status_code == 200
    assert signed_out.post_json("/api/members/emp-5/admin", {"admin": True}).status_code == 200

    allowed_in = signed_in(console, "dana-health-restricted", 5540).get(f"/api/projects/{project}/health")
    kept_out = signed_in(console, "ash-health-restricted", 5541).get(f"/api/projects/{project}/health")

    assert allowed_in.status_code == 403
    assert allowed_in.json()["message"] == "Only this project's leads and the team's admins can see its health."
    assert kept_out.status_code == 403
    assert "is restricted" in kept_out.json()["message"]
    assert health(signed_in(console, "lee-health-restricted", 5542), project)["project_id"] == project
    assert health(signed_in(console, "ada-health-restricted", 5543), project)["project_id"] == project
    assert health(signed_out, project)["project_id"] == project


def governed(client: ConsoleClient, project: str, path: str) -> tuple[dict[str, Any], ...]:
    """What the screens that govern memory show: a memory with its last use, the challenges, and the pins."""
    return (
        ask(client, "/api/memory", path=path),
        ask(client, "/api/challenges"),
        ask(client, f"/api/projects/{project}/pins"),
    )


def test_project_health_changes_nothing(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-unchanged", 5544)
    outdated = promote_keeping_both(in_project, TAX)
    doubted = promote_keeping_both(in_project, RETRIES)
    member_in(console, signed_out, project, "emp-2", "Dana Dev").call("challenge", path=doubted, reason="misled")
    console.clock.advance(days=61)
    sign_in_again(console, signed_out, "olive-health-unchanged", 5544)
    before = governed(signed_out, project, outdated)
    reached = watch_for_writes(monkeypatch)

    first = health(signed_out, project)
    again = health(signed_out, project)

    [declared] = [one for one in DECLARATIONS if one.path == "/projects/{project_id}/health"]
    assert (declared.method, declared.changes) == ("GET", False)
    assert reached == []
    # Reading it is no use of a memory, decides no challenge and pins nothing: it reads the same the second time.
    assert first == again
    assert sorted(paths(first["possibly_outdated"])) == sorted([outdated, doubted])
    assert paths(first["in_doubt"]) == [doubted]
    assert governed(signed_out, project, outdated) == before


# Coverage gaps (#572): files the project's sessions edited often lately that no memory is tied to


def gap(path: str, edits: int) -> dict[str, Any]:
    return {"repository": "billing-api", "path": path, "file": f"billing-api:{path}", "edits": edits}


def edit(session: Session, path: str, times: int = 1) -> None:
    for _ in range(times):
        session.edit(path)


def test_project_health_lists_often_edited_files_no_memory_is_tied_to_most_edited_first(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-gaps", 5545)
    promoted(in_project, tied_files=["billing-api:src/tax.py"])
    promoted(in_project, level="team", title="Ledgers close monthly", tied_files=["billing-api:src/ledger/**"])
    # A member's own personal memory is theirs, not the project's: the file it is tied to is still a gap.
    remember(in_project, title="Exports", tied_files=["billing-api:src/exports.py"])
    edit(in_project, "src/tax.py", 4)
    edit(in_project, "src/ledger/close.py", 2)
    edit(in_project, "src/webhooks.py", 3)
    edit(in_project, "src/exports.py")

    found = health(signed_out, project)

    assert found["coverage_days"] == 30
    assert found["coverage_gaps"] == [gap("src/webhooks.py", 3), gap("src/exports.py", 1)]


def test_coverage_gaps_count_only_the_project_s_edits_that_went_ahead_within_coverage_days(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-window", 5546)
    elsewhere = in_project.call("create_project", name="Payroll")["project_id"]
    edit(in_project, "src/old.py", 5)
    console.clock.advance(days=31)
    sign_in_again(console, signed_out, "olive-health-window", 5546)
    edit(in_project, "src/webhooks.py", 2)
    edit(in_project.in_project(elsewhere, "billing-api").as_session("payroll"), "src/payroll.py", 3)
    # Another session's edit of a file Olive's session holds is blocked, so it changes nothing and isn't counted.
    dana = member_in(console, signed_out, project, "emp-2", "Dana Dev")
    assert dana.edit("src/webhooks.py")["hookSpecificOutput"]["permissionDecision"] == "deny"

    found = health(signed_out, project)

    assert found["coverage_gaps"] == [gap("src/webhooks.py", 2)]


# Most relied on (#571): the project memory sessions were told most, and personal memory near the popular-memory bar

PNPM = {
    "title": "Use pnpm, not npm",
    "summary": "Every package in billing is managed with pnpm, never npm.",
    "type": "convention",
    "body": "We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
}
PNPM_PROMPT = "which package manager do we use for the billing packages?"


def recalled_in(session: Session, identifier: str, prompt: str = PNPM_PROMPT) -> list[str]:
    """A new session of the member's prompts once; the paths its recall told it."""
    told = session.as_session(identifier).prompt(prompt)
    return re.findall(r"projects/[^\s)\"]+\.md", json.dumps(told))


def test_project_health_lists_the_project_memory_recalled_in_the_most_sessions_within_relied_on_days(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-recalled", 5547)
    pnpm = promote_keeping_both(in_project, PNPM)
    dana = member_in(console, signed_out, project, "emp-2", "Dana Dev")
    # Long ago: past the window, so not counted.
    assert pnpm in recalled_in(in_project, "olive-long-ago")
    console.clock.advance(days=31)
    sign_in_again(console, signed_out, "olive-health-recalled", 5547)
    for each in ("olive-1", "olive-2"):
        assert pnpm in recalled_in(in_project, each)
    assert pnpm in recalled_in(dana, "dana-1")
    # Told once a session: the same prompt again in the same session adds nothing.
    in_project.as_session("olive-1").prompt(PNPM_PROMPT)
    # A member's own personal memory is theirs, not the project's, however often it is recalled.
    own = in_project.call("remember", **{**PNPM, "title": "pnpm workspaces", "summary": "pnpm workspaces."})["path"]

    found = health(signed_out, project)

    assert found["relied_on_days"] == 30
    [first, *_] = found["most_recalled"]
    assert first["path"] == pnpm
    assert first["title"] == PNPM["title"]
    assert first["author_name"] == "Olive Owner"
    assert first["sessions"] == 3
    assert own not in paths(found["most_recalled"])
    assert all(one["path"].startswith(f"projects/{project}/shared/") for one in found["most_recalled"])


def test_project_health_leaves_out_memory_retired_since_it_was_recalled(console: Console, signed_out: ConsoleClient) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-retired", 5548)
    pnpm = promote_keeping_both(in_project, PNPM)
    assert pnpm in recalled_in(in_project, "olive-before")
    assert paths(health(signed_out, project)["most_recalled"]) == [pnpm]

    assert signed_out.post_json("/api/memory/retire", {"path": pnpm}).status_code == 200

    assert pnpm not in paths(health(signed_out, project)["most_recalled"])


def test_project_health_lists_personal_memory_near_the_popular_memory_bar_by_distinct_other_readers(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, in_project = a_project(console, signed_out, "olive-health-near", 5549)
    dana = member_in(console, signed_out, project, "emp-2", "Dana Dev")
    ash = member_in(console, signed_out, project, "emp-3", "Ash Dev")
    near = dana.call("remember", **TAX)["path"]
    popular = dana.call("remember", **RETRIES)["path"]
    only_its_author = dana.call("remember", **EXPORTS)["path"]
    elsewhere = dana.in_project(in_project.call("create_project", name="Payroll")["project_id"], "payroll-api")
    other_project = elsewhere.call("remember", **{**TAX, "title": "Payroll tax"})["path"]
    for _ in range(3):
        ash.call("read", path=near)
    for reader in (in_project, ash):
        reader.call("read", path=popular)
    dana.call("read", path=only_its_author)
    ash.call("read", path=other_project)

    found = health(signed_out, project)

    assert found["popular_members"] == 2
    assert paths(found["nearly_popular"]) == [near]
    [listed] = found["nearly_popular"]
    assert listed["title"] == TAX["title"]
    assert listed["author_name"] == "Dana Dev"
    assert listed["readers"] == 1, "each member counts once however often they read it"
