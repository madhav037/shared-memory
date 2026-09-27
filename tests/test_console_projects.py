"""Projects in the console: creating them, naming them, who leads them and which repositories belong to them."""

from __future__ import annotations

import json
from typing import Any

from tests.support import Console, ConsoleClient, Session, add, create, fetch_project, signed_in_owner


def projects(client: ConsoleClient) -> list[dict[str, Any]]:
    response = client.get("/api/projects")
    assert response.status_code == 200, response.text
    listed: list[dict[str, Any]] = response.json()["projects"]
    return listed


def leads(project: dict[str, Any]) -> list[str]:
    return [lead["member_id"] for lead in project["leads"]]


def signed_in_member(
    console: Console, owner: ConsoleClient, member_id: str, github: str, account: int
) -> ConsoleClient:
    """A second member of the team, added by the owner and signed in to their own console session."""
    add(owner, member_id, f"Dana {member_id}", github)
    client = console.client()
    console.github.as_(account, github)
    client.sign_in()
    return client


def test_an_admin_creates_a_project_and_is_its_first_lead(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-projects-one", 701)

    created = create(signed_out, "Billing")

    assert created["name"] == "Billing"
    assert leads(created) == ["E1001"]
    assert created["you_lead"] is True
    assert created["you_may_change"] is True


def test_creating_a_project_from_claude_makes_the_creator_its_lead(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-projects-two", 702)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-projects-two", 703)
    dana_claude = Session(console.server, owner.call("reissue_token", member_id="emp-2")["personal_token"])

    made_by_dana = dana_claude.call("create_project", name="Payments")["project_id"]

    assert leads(fetch_project(signed_out, made_by_dana)) == ["emp-2"]
    assert [one["you_lead"] for one in projects(dana) if one["project_id"] == made_by_dana] == [True]
    dana.close()


def test_every_project_in_the_team_is_listed_with_its_leads(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-projects-three", 704)
    owner.call("create_project", name="Billing")
    create(signed_out, "Payments")

    listed = projects(signed_out)

    assert [(one["name"], leads(one)) for one in listed] == [("Billing", ["E1001"]), ("Payments", ["E1001"])]


def test_a_project_is_renamed_and_keeps_its_project_id(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-projects-four", 705)
    created = create(signed_out, "Biling")

    renamed = signed_out.post_json(f"/api/projects/{created['project_id']}/rename", {"name": "Billing"})

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Billing"
    assert renamed.json()["project_id"] == created["project_id"]


def test_a_lead_appoints_another_lead_and_an_admin_takes_one_off(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-projects-five", 706)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-projects-five", 707)
    ash = signed_in_member(console, signed_out, "emp-3", "ash-projects-five", 708)
    billing = create(signed_out, "Billing")["project_id"]

    signed_out.post_json(f"/api/projects/{billing}/leads", {"member_id": "emp-2"})
    appointed_by_a_lead = dana.post_json(f"/api/projects/{billing}/leads", {"member_id": "emp-3"})
    removed_by_a_lead = dana.post(f"/api/projects/{billing}/leads/emp-3/remove")
    removed_by_an_admin = signed_out.post(f"/api/projects/{billing}/leads/emp-3/remove")

    assert leads(appointed_by_a_lead.json()) == ["E1001", "emp-2", "emp-3"]
    assert removed_by_a_lead.status_code == 403
    assert "owner and its admins can take a lead off" in removed_by_a_lead.json()["message"]
    assert leads(removed_by_an_admin.json()) == ["E1001", "emp-2"]
    dana.close()
    ash.close()


def test_a_project_shows_its_repositories_with_the_settings_to_commit(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-projects-six", 709)
    billing = owner.call("create_project", name="Billing", repository="billing-api")["project_id"]

    added = signed_out.post_json(f"/api/projects/{billing}/repositories", {"name": "billing-web"})

    repositories = added.json()["repositories"]
    assert [one["name"] for one in repositories] == ["billing-api", "billing-web"]
    files = {file["path"]: file for file in repositories[1]["files"]}
    settings = json.loads(files[".claude/settings.json"]["contents"])
    assert settings["env"] == {"SHARED_MEMORY_PROJECT": billing, "SHARED_MEMORY_REPOSITORY": "billing-web"}
    assert settings["enabledPlugins"] == {"shared-memory@shared-memory": True}
    assert files[".codex/config.toml"]["agent"] == "Codex"
    assert 'X-Shared-Memory-Repository" = "billing-web"' in files[".codex/config.toml"]["contents"]


def test_a_lead_adds_and_removes_repositories_and_a_plain_member_cannot(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-projects-seven", 710)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-projects-seven", 711)
    ash = signed_in_member(console, signed_out, "emp-3", "ash-projects-seven", 712)
    billing = create(signed_out, "Billing")["project_id"]
    signed_out.post_json(f"/api/projects/{billing}/leads", {"member_id": "emp-2"})

    added_by_a_lead = dana.post_json(f"/api/projects/{billing}/repositories", {"name": "billing-api"})
    added_by_a_member = ash.post_json(f"/api/projects/{billing}/repositories", {"name": "billing-web"})
    removed_by_a_lead = dana.post(f"/api/projects/{billing}/repositories/billing-api/remove")

    assert [one["name"] for one in added_by_a_lead.json()["repositories"]] == ["billing-api"]
    assert added_by_a_member.status_code == 403
    assert "leads and the team's admins" in added_by_a_member.json()["message"]
    assert removed_by_a_lead.json()["repositories"] == []
    dana.close()
    ash.close()


def test_a_member_who_does_not_lead_a_project_cannot_rename_it(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-projects-eight", 713)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-projects-eight", 714)
    billing = create(signed_out, "Billing")["project_id"]

    refused = dana.post_json(f"/api/projects/{billing}/rename", {"name": "Dana's billing"})
    seen = fetch_project(dana, billing)

    assert refused.status_code == 403
    assert seen["you_may_change"] is False
    assert seen["you_lead"] is False
    dana.close()


def test_a_project_lead_reads_the_audit_log_for_their_own_projects_only(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-projects-nine", 715)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-projects-nine", 716)
    ash = signed_in_member(console, signed_out, "emp-3", "ash-projects-nine", 717)
    billing = create(signed_out, "Billing")["project_id"]
    payments = create(signed_out, "Payments")["project_id"]
    signed_out.post_json(f"/api/projects/{billing}/leads", {"member_id": "emp-2"})
    signed_out.post_json(f"/api/projects/{billing}/repositories", {"name": "billing-api"})
    signed_out.post_json(f"/api/projects/{payments}/repositories", {"name": "payments-api"})

    log = dana.get("/api/audit")
    refused = ash.get("/api/audit")

    assert log.status_code == 200, log.text
    assert {event["project_id"] for event in log.json()["events"]} == {billing}
    assert refused.status_code == 403
    assert "Only the team's owner, its admins and a project's leads" in refused.json()["message"]
    dana.close()
    ash.close()


def test_every_change_to_a_project_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-projects-ten", 718)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-projects-ten", 719)
    billing = create(signed_out, "Billing")["project_id"]

    signed_out.post_json(f"/api/projects/{billing}/rename", {"name": "Billing and invoicing"})
    signed_out.post_json(f"/api/projects/{billing}/leads", {"member_id": "emp-2"})
    signed_out.post_json(f"/api/projects/{billing}/repositories", {"name": "billing-api"})
    signed_out.post(f"/api/projects/{billing}/repositories/billing-api/remove")
    signed_out.post(f"/api/projects/{billing}/leads/emp-2/remove")

    log = [event for event in signed_out.get("/api/audit").json()["events"] if event["project_id"] == billing]
    assert [event["kind"] for event in log] == [
        "lead_removed",
        "repository_removed",
        "repository_added",
        "lead_appointed",
        "project_renamed",
        "project_created",
    ]
    assert [event["target"] for event in log][:4] == ["emp-2", "billing-api", "billing-api", "emp-2"]
    dana.close()


def test_an_admin_sees_a_project_of_their_team_and_nothing_else(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-projects-eleven", 720)

    missing = signed_out.get("/api/projects/not-a-project")
    changing_a_missing_one = signed_out.post_json("/api/projects/not-a-project/rename", {"name": "Nope"})

    assert missing.status_code == 403
    assert "not a project in your team" in missing.json()["message"]
    assert changing_a_missing_one.status_code == 403
