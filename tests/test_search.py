from __future__ import annotations

from typing import Any

import pytest

from tests.support import Session, Team


def remember(session: Session, title: str, body: str, type: str = "convention", summary: str | None = None) -> str:
    saved = session.call("remember", title=title, summary=summary or title, type=type, body=body)
    path: str = saved["path"]
    return path


def paths(results: dict[str, Any]) -> list[str]:
    return [section["path"] for section in results["results"]]


@pytest.fixture
def knowledge(owner: Session) -> dict[str, str]:
    return {
        "retries": remember(owner, "Charge retries", "When a card charge fails we try it again two more times, then give up."),
        "cents": remember(owner, "Money amounts", "All money amounts are stored as integer cents, never floats."),
        "staging": remember(
            owner, "Staging database", "The staging database is wiped and reseeded every night.", type="gotcha"
        ),
        "timeouts": remember(
            owner,
            "Gateway timeouts",
            "When the payment gateway is slow the client raises ERR_TIMEOUT after 30 seconds.",
            type="gotcha",
        ),
    }


def test_search_finds_a_memory_by_meaning(owner: Session, knowledge: dict[str, str]) -> None:
    results = owner.call("search", query="how do we handle retries")

    assert paths(results)[0] == knowledge["retries"]


def test_search_finds_a_memory_by_an_exact_identifier(owner: Session, knowledge: dict[str, str]) -> None:
    results = owner.call("search", query="ERR_TIMEOUT")

    assert paths(results)[0] == knowledge["timeouts"]


def test_search_results_carry_path_heading_level_author_and_summary(owner: Session) -> None:
    path = remember(owner, "Money amounts", "Stored as integer cents.", summary="Money is integer cents.")

    first = owner.call("search", query="how is money stored")["results"][0]

    assert first == {
        "path": path,
        "title": "Money amounts",
        "heading": "Money amounts",
        "level": "personal",
        "type": "convention",
        "author": "owner-1",
        "summary": "Money is integer cents.",
        "label": "your personal memory",
        "pending": [],
        "possibly_outdated": False,
    }


def test_search_points_at_the_matching_section_of_a_memory(owner: Session) -> None:
    body = "Overview of billing.\n\n## Refunds\n\nRefunds go back to the original card within five days.\n\n## Invoices\n\nInvoices are PDFs emailed monthly."
    path = remember(owner, "Billing basics", body, type="architecture")

    first = owner.call("search", query="how long does a refund take")["results"][0]

    assert (first["path"], first["heading"]) == (path, "Refunds")


def test_a_memory_is_searchable_as_soon_as_it_is_saved_edited_or_deleted(owner: Session) -> None:
    path = remember(owner, "Feature flags", "Flags live in LaunchDarkly.")
    owner.call("edit_memory", path=path, body="Flags live in the flagsmith service.")

    assert paths(owner.call("search", query="flagsmith"))[:1] == [path]

    owner.call("delete_memory", path=path)

    assert path not in paths(owner.call("search", query="flagsmith"))


def test_search_can_be_filtered_by_type_and_level(owner: Session, knowledge: dict[str, str]) -> None:
    gotchas = owner.call("search", query="database", type="gotcha")
    project_level = owner.call("search", query="database", level="project")

    assert set(paths(gotchas)) <= {knowledge["staging"], knowledge["timeouts"]}
    assert paths(project_level) == []


def test_other_members_personal_memory_is_labeled_as_not_accepted(team: Team, project: str, owner: Session) -> None:
    added = team.owner().call("add_member", member_id="emp-2", name="Dana Dev")
    dana = Session(team.server, added["personal_token"], project, "billing-api")
    path = remember(dana, "Webhook signatures", "Verify the Stripe webhook signature before parsing.")

    first = owner.call("search", query="webhook signature")["results"][0]

    assert (first["path"], first["label"]) == (path, "personal memory of emp-2, not accepted by the team")


def test_search_stays_within_the_sessions_project(team: Team, owner: Session) -> None:
    other_project = team.owner().call("create_project", name="Search")["project_id"]
    elsewhere = team.owner().in_project(other_project)
    remember(elsewhere, "Index shards", "Search indexes are split into eight shards.")

    assert paths(owner.call("search", query="index shards")) == []


def test_reindex_rebuilds_the_index_from_the_memory_files(team: Team, owner: Session, knowledge: dict[str, str]) -> None:
    before = owner.call("search", query="how do we handle retries")

    team.server.run_cli("reindex")

    assert owner.call("search", query="how do we handle retries") == before
