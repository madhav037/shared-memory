"""Extra foundations (ADR-0019): a project's leads add them beside the core four, from a session or the console."""

from __future__ import annotations

from typing import Any

from tests.support import (
    BUG,
    CENTS,
    SERVICES,
    Console,
    ConsoleClient,
    Crew,
    Session,
    Team,
    create,
    keepers,
    promote,
    remember,
    signed_in_owner,
)
from tests.test_console_projects import signed_in_member

SECURITY = "Security model"


def foundations(project: dict[str, Any]) -> list[tuple[str, str, bool]]:
    return [(one["slug"], one["name"], one["core"]) for one in project["foundations"]]


def test_a_lead_adds_a_foundation_from_a_session_and_promotes_into_it(owner: Session, project: str) -> None:
    added = owner.call("add_foundation", name=SECURITY)

    assert added["foundation"] == "security-model"
    result = promote(owner, CENTS, foundation="security-model")
    assert result["status"] == "promoted"
    assert result["path"].startswith(f"projects/{project}/shared/foundations/security-model/")
    memory = owner.call("read", path=result["path"])
    assert (memory["type"], memory["foundation"]) == ("convention", "security-model")


def test_an_extra_takes_any_type_but_a_known_issue(owner: Session) -> None:
    owner.call("add_foundation", name=SECURITY)

    assert promote(owner, {**CENTS, "title": "Tokens expire", "summary": "Tokens last an hour.", "body": "Access tokens expire after one hour."}, foundation="security-model")["status"] == "promoted"
    saved = owner.call("save_known_issue", **BUG)
    assert "already project memory" in owner.refusal(
        "promote", path=saved["path"], level="project", foundation="security-model"
    )


def test_a_core_type_still_belongs_in_its_own_foundation(owner: Session) -> None:
    owner.call("add_foundation", name=SECURITY)

    refused = owner.refusal("promote", path=remember(owner, SERVICES), level="project", foundation="security-model")

    assert "belongs in the architecture foundation" in refused


def test_a_foundation_nobody_added_is_refused_naming_the_ones_there_are(owner: Session) -> None:
    owner.call("add_foundation", name=SECURITY)

    refused = owner.refusal("promote", path=remember(owner, CENTS), level="project", foundation="api")

    assert "architecture, product, glossary, decisions, security-model" in refused


def test_a_name_that_repeats_a_foundation_or_has_no_letters_is_refused(owner: Session) -> None:
    owner.call("add_foundation", name=SECURITY)

    assert "already has" in owner.refusal("add_foundation", name="security MODEL!")
    assert "already has" in owner.refusal("add_foundation", name="Architecture")
    assert "letters or digits" in owner.refusal("add_foundation", name="  ?!  ")


def test_only_a_project_lead_adds_a_foundation_from_a_session(dana: Session) -> None:
    assert "Only this project's leads" in dana.refusal("add_foundation", name=SECURITY)


def test_each_project_has_its_own_extras(team: Team, owner: Session) -> None:
    owner.call("add_foundation", name=SECURITY)
    other = team.owner().in_project(team.owner().call("create_project", name="Checkout")["project_id"], "checkout")

    refused = other.refusal("promote", path=remember(other, CENTS), level="project", foundation="security-model")

    assert "no 'security-model' foundation" in refused


def test_a_lead_adds_and_removes_an_extra_in_the_console(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1901)
    where = f"/api/projects/{crew.project}/foundations"

    added = signed_out.post_json(where, {"name": SECURITY})

    assert added.status_code == 200
    assert foundations(added.json())[-1] == ("security-model", SECURITY, False)
    assert foundations(added.json())[0] == ("architecture", "Architecture", True)
    assert crew.assign("emp-kit", "security-model").status_code == 200
    removed = signed_out.post(f"{where}/security-model/remove")
    assert removed.status_code == 200
    assert [slug for slug, _, _ in foundations(removed.json())] == ["architecture", "product", "glossary", "decisions"]
    assert crew.assign("emp-kit", "security-model").status_code == 403


def test_the_console_refuses_a_duplicate_a_core_removal_and_an_unknown_one(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 1902)
    where = f"/api/projects/{crew.project}/foundations"

    duplicate = signed_out.post_json(where, {"name": "Glossary"})
    core = signed_out.post(f"{where}/glossary/remove")
    unknown = signed_out.post(f"{where}/nope/remove")

    assert duplicate.status_code == core.status_code == unknown.status_code == 403
    assert "already has" in duplicate.json()["message"]
    assert "core four" in core.json()["message"]
    assert "no 'nope' foundation" in unknown.json()["message"]


def test_an_extra_holding_active_memory_is_not_removed(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1903)
    crew.owner.call("add_foundation", name=SECURITY)
    held = promote(crew.owner, CENTS, foundation="security-model")["path"]
    where = f"/api/projects/{crew.project}/foundations/security-model/remove"

    refused = signed_out.post(where)

    assert refused.status_code == 403
    assert "still holds active memory" in refused.json()["message"]
    crew.owner.call("retire", path=held)
    assert signed_out.post(where).status_code == 200


def test_only_a_lead_or_an_admin_changes_the_extras_in_the_console(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-extras-1904", 1904)
    plain = signed_in_member(console, signed_out, "emp-2", "plain-extras-1904", 1905)
    billing = create(signed_out, "Billing")["project_id"]
    where = f"/api/projects/{billing}/foundations"
    signed_out.post_json(where, {"name": SECURITY})

    added = plain.post_json(where, {"name": "API contract"})
    removed = plain.post(f"{where}/security-model/remove")

    assert added.status_code == removed.status_code == 403
    assert "leads and the team's admins" in added.json()["message"]
    assert signed_out.post(f"{where}/security-model/remove").status_code == 200
    plain.close()


def test_a_keeper_of_an_extra_is_listed_with_it(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1906)
    signed_out.post_json(f"/api/projects/{crew.project}/foundations", {"name": SECURITY})

    assigned = crew.assign("emp-kit", "security-model")

    assert keepers(assigned.json(), "security-model") == ["emp-kit"]


def test_adding_and_removing_an_extra_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1907)
    where = f"/api/projects/{crew.project}/foundations"

    signed_out.post_json(where, {"name": SECURITY})
    signed_out.post(f"{where}/security-model/remove")

    log = [e for e in signed_out.get("/api/audit").json()["events"] if e["project_id"] == crew.project][:2]
    assert [(e["kind"], e["target"]) for e in log] == [
        ("foundation_removed", "security-model"),
        ("foundation_added", "security-model"),
    ]
    assert log[1]["detail"]["name"] == SECURITY


def test_an_extra_with_an_open_add_challenge_is_not_removed(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1908)
    crew.owner.call("add_foundation", name=SECURITY)
    raised = promote(crew.rae, CENTS, foundation="security-model")
    where = f"/api/projects/{crew.project}/foundations/security-model/remove"

    refused = signed_out.post(where)

    assert refused.status_code == 403
    assert "waiting to join" in refused.json()["message"]
    crew.owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")
    assert signed_out.post(where).status_code == 200
