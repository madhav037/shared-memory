"""Onboarding progress (#617, spec #614): a session records how far onboarding has got for one repository or outside
source, and the project's leads and the company's admins read it in project settings. Promoted and waiting-on-challenge
counts come from the audit log's imports; the session gives the left-out count."""

from __future__ import annotations

from typing import Any

from shared_memory.console_contract import DECLARATIONS
from tests.support import (
    Console,
    ConsoleClient,
    Session,
    add,
    ask,
    promote_now,
    signed_in,
    signed_in_owner,
)

CENTS = {
    "title": "Money amounts",
    "summary": "Money is integer cents.",
    "type": "convention",
    "body": "All money amounts are stored as integer cents, never floats.",
}
RETRIES = {
    "title": "Webhooks retry three times",
    "summary": "A failed webhook is retried three times with backoff.",
    "type": "gotcha",
    "body": "The provider retries a failed webhook three times, an hour apart, before it gives up.",
}


def progress(client: ConsoleClient, project: str) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/onboarding")


def entry(listed: dict[str, Any], **which: str | None) -> dict[str, Any]:
    found: dict[str, Any]
    (found,) = [
        one
        for one in listed["entries"]
        if (one["repository"], one["outside_source"]) == (which.get("repository"), which.get("outside_source"))
    ]
    return found


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session]:
    owner = signed_in_owner(console, client, github, account)
    project: str = owner.call("create_project", name="Billing")["project_id"]
    return project, owner.in_project(project, "billing-api")


def member_in(console: Console, client: ConsoleClient, project: str, member_id: str, name: str, github: str) -> Session:
    added = add(client, member_id, name, github=github)
    return Session(console.server, added["personal_token"]).in_project(project, "billing-api")


def imported(
    session: Session, memory: dict[str, str], source: str, author: str = "emp-2", supersede: str | None = None
) -> dict[str, Any]:
    """Promote an import in its writer's name, keeping both with any similar memory but the one it supersedes."""
    personal = session.call("remember", **memory)["path"]
    result: dict[str, Any] = session.call(
        "promote", path=personal, level="project", author=author, imported_from=source
    )
    if result["status"] != "similar_memories":
        return result
    resolutions = {one["path"]: "supersede" if one["path"] == supersede else "keep_both" for one in result["similar"]}
    answered: dict[str, Any] = session.call(
        "promote", path=personal, level="project", reference=result["reference"], resolutions=resolutions
    )
    return answered


# Recording, in a session


def test_a_session_records_a_progress_entry_and_recording_again_replaces_it(owner: Session) -> None:
    first = owner.call("record_onboarding_progress", status="partly_done", repository="billing-api", left_out=3)
    again = owner.call("record_onboarding_progress", status="done", repository="billing-api", left_out=5)

    assert (first["status"], again["status"]) == ("partly_done", "done")
    steps = owner.call("onboard")
    assert "billing-api: done" in steps
    assert "partly_done" not in steps.split("## Progress so far")[1]


def test_progress_is_recorded_for_one_repository_or_one_outside_source(owner: Session) -> None:
    neither = owner.refusal("record_onboarding_progress", status="done")
    both = owner.refusal("record_onboarding_progress", status="done", repository="billing-api", outside_source="wiki")
    unknown_kind = owner.refusal("record_onboarding_progress", status="done", outside_source="slack")
    unknown_status = owner.refusal("record_onboarding_progress", status="finished", repository="billing-api")

    for refusal in (neither, both):
        assert "repository" in refusal and "outside_source" in refusal
    assert "wiki" in unknown_kind and "interview" in unknown_kind
    assert "not_started" in unknown_status and "partly_done" in unknown_status


def test_the_steps_tell_the_agent_to_read_progress_first_and_record_it_per_repository_and_source(
    owner: Session,
) -> None:
    steps = owner.call("onboard")

    assert "record_onboarding_progress" in steps
    assert "Progress so far" in steps
    assert steps.index("Read the progress so far") < steps.index("## 1. ")


# Reading, in the console


def test_reading_progress_gives_status_who_when_and_counts_from_the_audit_log(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, owner = a_project(console, signed_out, "olive-progress-counts", 7901)
    dana = member_in(console, signed_out, project, "emp-2", "Dana Dev", "dana-progress-counts")
    member_in(console, signed_out, project, "emp-3", "Cole Coder", "cole-progress-counts")
    refunds = {**CENTS, "title": "Refunds", "body": "Refunds go back to the card."}
    tax = {**CENTS, "title": "Tax", "body": "Tax is added at checkout."}
    for memory, source in ((CENTS, "billing-api:CLAUDE.md"), (refunds, "commit:billing-api@3f9c2ab"), (tax, "wiki:Tax")):
        assert imported(owner, memory, source)["status"] == "promoted", source
    # One import supersedes a memory Dana wrote, so it waits on her challenge decision.
    existing = promote_now(dana, RETRIES)
    superseding = {**RETRIES, "body": RETRIES["body"] + " Then twice more."}
    raised = imported(owner, superseding, "billing-api:AGENTS.md", author="emp-3", supersede=existing)
    assert raised["status"] == "challenge_raised", raised
    owner.call("record_onboarding_progress", status="done", repository="billing-api", left_out=4)
    owner.call("record_onboarding_progress", status="partly_done", outside_source="wiki", left_out=1)

    listed = progress(signed_out, project)

    repository = entry(listed, repository="billing-api")
    assert (repository["status"], repository["recorded_by"], repository["recorded_by_name"]) == (
        "done",
        "E1001",
        "Olive Owner",
    )
    assert repository["recorded_at"]
    assert (repository["promoted"], repository["waiting_on_challenge"], repository["left_out"]) == (2, 1, 4)
    wiki = entry(listed, outside_source="wiki")
    assert (wiki["status"], wiki["promoted"], wiki["waiting_on_challenge"], wiki["left_out"]) == ("partly_done", 1, 0, 1)
    assert listed["everyone"] is True


def test_project_settings_shows_every_entry_to_leads_and_admins_and_others_only_their_own(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, owner = a_project(console, signed_out, "olive-progress-who", 7902)
    dana = member_in(console, signed_out, project, "emp-2", "Dana Dev", "dana-progress-who")
    member_in(console, signed_out, project, "emp-3", "Lee Lead", "lee-progress-who")
    member_in(console, signed_out, project, "emp-4", "Ada Admin", "ada-progress-who")
    assert signed_out.post_json(f"/api/projects/{project}/leads", {"member_id": "emp-3"}).status_code == 200
    assert signed_out.post_json("/api/members/emp-4/admin", {"admin": True}).status_code == 200
    owner.call("record_onboarding_progress", status="done", repository="billing-api")
    dana.call("record_onboarding_progress", status="partly_done", outside_source="ticket")

    lead = progress(signed_in(console, "lee-progress-who", 7903), project)
    admin = progress(signed_in(console, "ada-progress-who", 7904), project)
    own = progress(signed_in(console, "dana-progress-who", 7905), project)

    for everyone in (lead, admin):
        assert everyone["everyone"] is True
        assert len(everyone["entries"]) == 2
    assert own["everyone"] is False
    assert [(one["outside_source"], one["recorded_by"]) for one in own["entries"]] == [("ticket", "emp-2")]


def test_the_api_contract_declares_onboarding_progress() -> None:
    declared = {(one.path, one.method) for one in DECLARATIONS}

    assert ("/projects/{project_id}/onboarding", "GET") in declared
