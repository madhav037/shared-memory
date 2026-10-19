"""Keepers (ADR-0019): a project's leads assign them in the console, and they decide their foundation's challenges."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, add, added_context, create, fetch_project, signed_in_owner
from tests.test_console_projects import signed_in_member
from tests.test_foundations import (
    CENTS,
    FOUNDATION_HEADING,
    INVOICE,
    SERVICES,
    SERVICES_TWO,
    promote,
    supersede,
)


class Crew:
    """A project led by the console's owner, with a keeper-to-be (Kit), a raiser (Rae) and a bystander (Bea)."""

    def __init__(self, console: Console, client: ConsoleClient, account: int) -> None:
        self.client = client
        owner = signed_in_owner(console, client, f"olive-keepers-{account}", account)
        self.project: str = owner.call("create_project", name="Billing")["project_id"]
        self.owner = owner.in_project(self.project, "billing-api")
        self.kit = self._add(console, "emp-kit", "Kit Keeper")
        self.rae = self._add(console, "emp-rae", "Rae Raiser")
        self.bea = self._add(console, "emp-bea", "Bea Bystander")

    def _add(self, console: Console, member_id: str, name: str) -> Session:
        token = add(self.client, member_id, name)["personal_token"]
        return Session(console.server, token, self.project, "billing-api")

    def assign(self, member_id: str, foundation: str = "architecture") -> Any:
        where = f"/api/projects/{self.project}/foundations/{foundation}/keepers"
        return self.client.post_json(where, {"member_id": member_id})


def keepers(project: dict[str, Any], foundation: str) -> list[str]:
    (found,) = [one for one in project["foundations"] if one["slug"] == foundation]
    return [keeper["member_id"] for keeper in found["keepers"]]


def briefing(session: Session) -> str:
    return added_context(session.start())


def test_a_keeper_decides_challenges_to_their_foundation_as_a_keeper(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1801)
    crew.assign("emp-kit")
    raised = promote(crew.rae, SERVICES, reasoning="Billing belongs in architecture.")

    heard = briefing(crew.kit)
    accepted = crew.kit.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert FOUNDATION_HEADING in heard
    assert f"Challenge {raised['challenge_id']} by emp-rae, yours to decide as a keeper of the foundation" in heard
    assert accepted["status"] == "accepted"
    assert "/foundations/architecture/" in accepted["path"]
    decided = [e for e in signed_out.get("/api/audit").json()["events"] if e["kind"] == "challenge_decided"]
    assert decided[0]["detail"]["decided_as"] == "keeper"


def test_challenges_to_other_foundations_do_not_wait_on_a_keeper(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1802)
    crew.assign("emp-kit")
    raised = promote(crew.rae, INVOICE, foundation="glossary")

    refusal = crew.kit.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "keeper of the glossary foundation" in refusal
    assert FOUNDATION_HEADING not in briefing(crew.kit)
    assert FOUNDATION_HEADING in briefing(crew.owner)


def test_a_keeper_never_decides_their_own_challenge(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1803)
    crew.assign("emp-kit")

    kept = promote(crew.kit, SERVICES, foundation="architecture")
    other = promote(crew.kit, INVOICE, foundation="glossary")

    assert kept["status"] == "promoted"
    assert other["status"] == "challenge_raised"
    assert "You raised" in crew.kit.refusal("decide_challenge", challenge_id=other["challenge_id"], decision="accept")


def test_a_keepers_own_change_to_their_foundation_lands_at_once(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1804)
    held = promote(crew.owner, SERVICES)["path"]
    crew.assign("emp-kit")

    superseded = supersede(crew.kit, SERVICES_TWO, held)
    retired = crew.kit.call("retire", path=superseded["path"])

    assert superseded["status"] == "promoted"
    assert crew.owner.call("read", path=held)["status"] == "superseded"
    assert retired["status"] == "retired"


def test_a_keeper_of_one_foundation_challenges_another_like_anyone(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1805)
    crew.assign("emp-kit", "product")

    assert promote(crew.kit, SERVICES)["status"] == "challenge_raised"
    assert promote(crew.rae, CENTS)["status"] == "promoted"


def test_removing_a_keeper_from_the_team_drops_their_assignments(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1806)
    crew.assign("emp-kit")
    crew.assign("emp-kit", "decisions")

    signed_out.post("/api/members/emp-kit/remove")

    project = fetch_project(signed_out, crew.project)
    assert keepers(project, "architecture") == []
    assert keepers(project, "decisions") == []
    dropped = [e for e in signed_out.get("/api/audit").json()["events"] if e["kind"] == "keeper_removed"]
    assert sorted((e["target"], e["detail"]["foundation"], e["detail"]["dropped"]) for e in dropped) == [
        ("emp-kit", "architecture", True),
        ("emp-kit", "decisions", True),
    ]


def test_revoking_access_to_a_restricted_project_drops_a_keepers_assignments(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 1807)
    signed_out.post_json(f"/api/projects/{crew.project}/restrict", {"restricted": True})
    signed_out.post_json(f"/api/projects/{crew.project}/access", {"member_id": "emp-kit"})
    signed_out.post_json(f"/api/projects/{crew.project}/access", {"member_id": "emp-bea"})
    crew.assign("emp-kit")
    crew.assign("emp-bea", "product")

    signed_out.post(f"/api/projects/{crew.project}/access/emp-kit/remove")

    project = fetch_project(signed_out, crew.project)
    assert keepers(project, "architecture") == []
    assert keepers(project, "product") == ["emp-bea"]


def test_only_a_member_who_can_reach_a_restricted_project_is_made_a_keeper(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 1808)
    signed_out.post_json(f"/api/projects/{crew.project}/restrict", {"restricted": True})

    refused = crew.assign("emp-kit")

    assert refused.status_code == 403
    assert "can't reach" in refused.json()["message"]


def test_leads_and_admins_assign_and_remove_keepers_and_nobody_else(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-keepers-1809", 1809)
    lead = signed_in_member(console, signed_out, "emp-2", "lead-keepers-1809", 1810)
    plain = signed_in_member(console, signed_out, "emp-3", "plain-keepers-1809", 1811)
    billing = create(signed_out, "Billing")["project_id"]
    signed_out.post_json(f"/api/projects/{billing}/leads", {"member_id": "emp-2"})
    where = f"/api/projects/{billing}/foundations/architecture/keepers"

    by_a_member = plain.post_json(where, {"member_id": "emp-3"})
    by_a_lead = lead.post_json(where, {"member_id": "emp-3"})
    removed_by_a_member = plain.post(f"{where}/emp-3/remove")
    removed_by_an_admin = signed_out.post(f"{where}/emp-3/remove")

    assert by_a_member.status_code == 403
    assert "leads and the team's admins" in by_a_member.json()["message"]
    assert keepers(by_a_lead.json(), "architecture") == ["emp-3"]
    assert removed_by_a_member.status_code == 403
    assert keepers(removed_by_an_admin.json(), "architecture") == []
    assert signed_out.post(f"{where}/emp-3/remove").status_code == 403
    for client in (lead, plain):
        client.close()


def test_the_project_lists_each_foundation_with_its_keepers(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1812)
    assigned = crew.assign("emp-kit", "decisions")

    assert [one["slug"] for one in assigned.json()["foundations"]] == ["architecture", "product", "glossary", "decisions"]
    assert keepers(assigned.json(), "decisions") == ["emp-kit"]
    assert keepers(fetch_project(signed_out, crew.project), "architecture") == []
    unknown = signed_out.post_json(f"/api/projects/{crew.project}/foundations/nope/keepers", {"member_id": "emp-kit"})
    assert unknown.status_code == 403


def test_assigning_and_removing_a_keeper_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1813)

    crew.assign("emp-kit")
    signed_out.post(f"/api/projects/{crew.project}/foundations/architecture/keepers/emp-kit/remove")

    log = [e for e in signed_out.get("/api/audit").json()["events"] if e["project_id"] == crew.project][:2]
    assert [(e["kind"], e["target"], e["detail"]["foundation"]) for e in log] == [
        ("keeper_removed", "emp-kit", "architecture"),
        ("keeper_assigned", "emp-kit", "architecture"),
    ]
