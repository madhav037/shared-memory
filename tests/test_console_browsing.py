"""Browsing and searching memory in the console: the same memory a member's Claude would see."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from tests.support import Console, ConsoleClient, Session


def signed_in_owner(console: Console, client: ConsoleClient, github: str, account: int) -> Session:
    """A team whose owner is signed in to the console, and that owner's Claude session."""
    _, owner_token = console.a_team(github)
    console.github.as_(account, github)
    client.sign_in()
    return Session(console.server, owner_token)


def ask(client: ConsoleClient, url: str, **asked: Any) -> dict[str, Any]:
    response = client.get(f"{url}?{urlencode({k: v for k, v in asked.items() if v is not None})}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_member_sees_the_projects_they_can_reach(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-browse-one", 301)
    owner.call("create_project", name="Billing")
    owner.call("create_project", name="Payments")

    projects = ask(signed_out, "/api/projects")

    assert [project["name"] for project in projects["projects"]] == ["Billing", "Payments"]


def test_a_project_shows_its_memory_as_a_tree_with_summaries(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-browse-two", 302)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.in_project(project, "billing-api").call(
        "remember",
        title="Use pnpm, not npm",
        summary="Billing uses pnpm.",
        type="convention",
        body="We use pnpm for every package.",
    )

    tree = ask(signed_out, f"/api/projects/{project}/tree")

    memories = [memory for folder in tree["folders"] for memory in folder["memories"]]
    assert [(memory["title"], memory["summary"]) for memory in memories] == [("Use pnpm, not npm", "Billing uses pnpm.")]


def test_a_memory_reads_in_full_with_its_details(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-browse-three", 303)
    project = owner.call("create_project", name="Billing")["project_id"]
    saved = owner.in_project(project, "billing-api").call(
        "remember",
        title="Staging resets nightly",
        summary="Staging is wiped at 02:17 UTC.",
        type="gotcha",
        body="The staging database is wiped and reseeded every night at 02:17 UTC.",
    )

    memory = ask(signed_out, f"/api/projects/{project}/memory", path=saved["path"])

    assert memory["title"] == "Staging resets nightly"
    assert memory["type"] == "gotcha"
    assert memory["author"] == "E1001"
    assert memory["level"] == "personal"
    assert memory["status"] == "active"
    assert "02:17 UTC" in memory["body"]
    assert memory["pending"] == []


def test_a_memory_shows_the_challenges_it_is_waiting_on(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-browse-four", 304)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    first = in_project.call(
        "remember", title="Use pnpm, not npm", summary="Billing uses pnpm.", type="convention", body="We use pnpm."
    )["path"]
    promoted = in_project.call("promote", path=first, level="project")
    dana = Session(console.server, owner.call("add_member", employee_id="emp-2", name="Dana Dev")["personal_token"])
    challenger = dana.in_project(project, "billing-api").call(
        "remember", title="Use npm, not pnpm", summary="Billing uses npm.", type="convention", body="We use npm."
    )["path"]
    similar = dana.in_project(project, "billing-api").call("promote", path=challenger, level="project")
    dana.in_project(project, "billing-api").call(
        "promote",
        path=challenger,
        level="project",
        reference=similar["reference"],
        resolutions={s["path"]: "supersede" for s in similar["similar"]},
    )

    challenged = ask(signed_out, f"/api/projects/{project}/memory", path=promoted["path"])
    pending = ask(signed_out, f"/api/projects/{project}/memory", path=challenger)

    assert [challenge["kind"] for challenge in challenged["open_challenges"]] == ["supersede"]
    assert [challenge["kind"] for challenge in pending["pending"]] == ["supersede"]


def test_search_finds_memories_by_meaning_and_by_exact_words(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-browse-five", 305)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.in_project(project, "billing-api").call(
        "remember",
        title="Use pnpm, not npm",
        summary="Every package in billing is managed with pnpm, never npm.",
        type="convention",
        body="We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
    )

    by_meaning = ask(signed_out, f"/api/projects/{project}/search", query="which package manager do we use")
    by_word = ask(signed_out, f"/api/projects/{project}/search", query="pnpm")
    filtered = ask(signed_out, f"/api/projects/{project}/search", query="pnpm", type="gotcha")

    assert [hit["title"] for hit in by_meaning["results"]] == ["Use pnpm, not npm"]
    assert [hit["title"] for hit in by_word["results"]] == ["Use pnpm, not npm"]
    assert by_word["results"][0]["label"] == "your personal memory"
    assert filtered["results"] == []


def test_another_members_personal_memory_is_labelled_as_not_accepted(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-browse-six", 306)
    project = owner.call("create_project", name="Billing")["project_id"]
    dana = Session(console.server, owner.call("add_member", employee_id="emp-2", name="Dana Dev")["personal_token"])
    dana.in_project(project, "billing-api").call(
        "remember",
        title="Dana's own note",
        summary="Dana keeps fixtures in a scratch folder.",
        type="convention",
        body="Dana keeps test fixtures in a scratch folder while working.",
    )

    found = ask(signed_out, f"/api/projects/{project}/search", query="fixtures scratch folder")

    assert found["results"][0]["label"] == "personal memory of emp-2, not accepted by the team"


def test_browsing_needs_a_signed_in_member_and_a_project_of_their_team(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_out_answer = signed_out.get("/api/projects")
    owner = signed_in_owner(console, signed_out, "olive-browse-seven", 307)
    owner.call("create_project", name="Billing")

    stranger_project = signed_out.get("/api/projects/not-a-project/tree")

    assert signed_out_answer.status_code == 401
    assert stranger_project.status_code == 403
    assert "not a project in your team" in stranger_project.json()["message"]
