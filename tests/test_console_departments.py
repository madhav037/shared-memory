"""Departments in the console (ADR-0032): who makes them, who leads them, and which projects are in them.

A department groups a company's projects, one level deep, and a project sits in at most one. Admins create, rename
and remove departments and name their department leads; a department lead names another lead and moves projects in
and out. Nothing about memory changes yet: these tests drive the console's JSON API and a session's tools over HTTP.
"""

from __future__ import annotations

from typing import Any

import httpx

from tests.support import Console, ConsoleClient, add, create, fetch_project, signed_in_owner


def signed_in_member(
    console: Console, owner: ConsoleClient, member_id: str, github: str, account: int
) -> ConsoleClient:
    """A member of the company who is not an admin, added by the owner and signed in to their own console session."""
    add(owner, member_id, f"Dana {member_id}", github)
    client = console.client()
    console.github.as_(account, github)
    client.sign_in()
    return client


def departments(client: ConsoleClient) -> list[dict[str, Any]]:
    response = client.get("/api/departments")
    assert response.status_code == 200, response.text
    listed: list[dict[str, Any]] = response.json()["departments"]
    return listed


def answered(response: httpx.Response) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    listed: list[dict[str, Any]] = response.json()["departments"]
    return listed


def make(client: ConsoleClient, name: str) -> dict[str, Any]:
    """Create a department through the console, and return it as listed."""
    listed = answered(client.post_json("/api/departments", {"name": name}))
    return next(one for one in listed if one["name"] == name)


def named(listed: list[dict[str, Any]], department_id: str) -> dict[str, Any]:
    return next(one for one in listed if one["department_id"] == department_id)


def leads(department: dict[str, Any]) -> list[str]:
    return [lead["member_id"] for lead in department["leads"]]


def projects_in(department: dict[str, Any]) -> list[str]:
    return [project["project_id"] for project in department["projects"]]


def test_an_admin_creates_a_department_names_a_lead_and_moves_a_project_in(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-departments-one", 1801)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-departments-one", 1802)
    billing = create(signed_out, "Billing")["project_id"]

    payments = make(signed_out, "Payments")
    signed_out.post_json(f"/api/departments/{payments['department_id']}/leads", {"member_id": "emp-2"})
    moved = signed_out.post_json(f"/api/departments/{payments['department_id']}/projects", {"project_id": billing})

    department = named(answered(moved), payments["department_id"])
    assert department["name"] == "Payments"
    assert leads(department) == ["emp-2"]
    assert projects_in(department) == [billing]
    in_the_list = next(one for one in signed_out.get("/api/projects").json()["projects"] if one["project_id"] == billing)
    assert in_the_list["department"] == {"department_id": payments["department_id"], "name": "Payments"}
    assert fetch_project(signed_out, billing)["department"] == {
        "department_id": payments["department_id"],
        "name": "Payments",
    }
    assert named(departments(dana), payments["department_id"])["you_lead"] is True
    dana.close()


def test_a_project_in_no_department_says_so(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-departments-two", 1803)
    billing = create(signed_out, "Billing")["project_id"]

    assert fetch_project(signed_out, billing)["department"] is None


def test_a_department_lead_adds_a_second_lead_and_moves_another_project_in(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-departments-three", 1804)
    dana = signed_in_member(console, signed_out, "emp-2", "dana-departments-three", 1805)
    ash = signed_in_member(console, signed_out, "emp-3", "ash-departments-three", 1806)
    billing = create(signed_out, "Billing")["project_id"]
    ledger = create(signed_out, "Ledger")["project_id"]
    payments = make(signed_out, "Payments")["department_id"]
    signed_out.post_json(f"/api/departments/{payments}/leads", {"member_id": "emp-2"})
    signed_out.post_json(f"/api/departments/{payments}/projects", {"project_id": billing})

    second_lead = dana.post_json(f"/api/departments/{payments}/leads", {"member_id": "emp-3"})
    moved_in = dana.post_json(f"/api/departments/{payments}/projects", {"project_id": ledger})
    moved_out = ash.post(f"/api/departments/{payments}/projects/{billing}/remove")

    assert leads(named(answered(second_lead), payments)) == ["emp-2", "emp-3"]
    assert projects_in(named(answered(moved_in), payments)) == [billing, ledger]
    assert projects_in(named(answered(moved_out), payments)) == [ledger]
    dana.close()
    ash.close()


def test_a_member_who_neither_runs_the_company_nor_leads_the_department_cannot_change_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-departments-four", 1807)
    ash = signed_in_member(console, signed_out, "emp-3", "ash-departments-four", 1808)
    billing = create(signed_out, "Billing")["project_id"]
    payments = make(signed_out, "Payments")["department_id"]

    refusals = [
        ash.post_json("/api/departments", {"name": "Platform"}),
        ash.post_json(f"/api/departments/{payments}/rename", {"name": "Money"}),
        ash.post_json(f"/api/departments/{payments}/leads", {"member_id": "emp-3"}),
        ash.post_json(f"/api/departments/{payments}/projects", {"project_id": billing}),
        ash.post(f"/api/departments/{payments}/remove"),
    ]

    assert [refused.status_code for refused in refusals] == [403] * 5
    assert "department's leads and the company's admins" in refusals[2].json()["message"]
    department = named(departments(signed_out), payments)
    assert (department["name"], leads(department), projects_in(department)) == ("Payments", [], [])
    assert named(departments(ash), payments)["you_may_change"] is False
    ash.close()


def test_a_project_cannot_be_in_two_departments(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-departments-five", 1809)
    billing = create(signed_out, "Billing")["project_id"]
    payments = make(signed_out, "Payments")["department_id"]
    platform = make(signed_out, "Platform")["department_id"]
    signed_out.post_json(f"/api/departments/{payments}/projects", {"project_id": billing})

    refused = signed_out.post_json(f"/api/departments/{platform}/projects", {"project_id": billing})

    assert refused.status_code == 403
    assert "already in the department 'Payments'" in refused.json()["message"]
    listed = departments(signed_out)
    assert (projects_in(named(listed, payments)), projects_in(named(listed, platform))) == ([billing], [])


def test_removing_a_department_leaves_its_projects_in_no_department(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-departments-six", 1810)
    billing = create(signed_out, "Billing")["project_id"]
    payments = make(signed_out, "Payments")["department_id"]
    signed_out.post_json(f"/api/departments/{payments}/projects", {"project_id": billing})

    removed = signed_out.post(f"/api/departments/{payments}/remove")

    assert answered(removed) == []
    assert fetch_project(signed_out, billing)["department"] is None
    again = signed_out.post_json("/api/departments/does-not-exist/projects", {"project_id": billing})
    assert again.status_code == 403
    assert "not a department in your company" in again.json()["message"]


def test_an_admin_renames_a_department_and_names_stay_unique(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-departments-seven", 1811)
    payments = make(signed_out, "Payments")["department_id"]
    make(signed_out, "Platform")

    renamed = signed_out.post_json(f"/api/departments/{payments}/rename", {"name": "Money"})
    clashing = signed_out.post_json(f"/api/departments/{payments}/rename", {"name": "platform"})
    empty = signed_out.post_json("/api/departments", {"name": "  "})

    assert named(answered(renamed), payments)["name"] == "Money"
    assert clashing.status_code == 403
    assert "already a department called" in clashing.json()["message"]
    assert empty.status_code == 403


def test_department_changes_leads_and_project_moves_are_in_the_audit_log(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-departments-eight", 1812)
    signed_in_member(console, signed_out, "emp-2", "dana-departments-eight", 1813).close()
    billing = create(signed_out, "Billing")["project_id"]
    payments = make(signed_out, "Payments")["department_id"]

    signed_out.post_json(f"/api/departments/{payments}/rename", {"name": "Money"})
    signed_out.post_json(f"/api/departments/{payments}/leads", {"member_id": "emp-2"})
    signed_out.post_json(f"/api/departments/{payments}/projects", {"project_id": billing})
    signed_out.post(f"/api/departments/{payments}/projects/{billing}/remove")
    signed_out.post(f"/api/departments/{payments}/leads/emp-2/remove")
    signed_out.post(f"/api/departments/{payments}/remove")

    events = signed_out.get("/api/audit").json()["events"]
    kinds = [event["kind"] for event in events if event["kind"].startswith(("department_", "project_moved"))]
    assert kinds == [
        "department_removed",
        "department_lead_removed",
        "project_moved",
        "project_moved",
        "department_lead_appointed",
        "department_renamed",
        "department_created",
    ]
    moves = [event for event in events if event["kind"] == "project_moved"]
    assert [(move["project_id"], move["detail"]) for move in moves] == [
        (billing, {"department_id": None, "from_department_id": payments}),
        (billing, {"department_id": payments, "from_department_id": None}),
    ]
    assert {event["target"] for event in events if event["kind"].startswith("department_")} == {payments}


def test_a_session_learns_its_projects_department(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-departments-nine", 1814)
    billing = create(signed_out, "Billing")["project_id"]
    ledger = create(signed_out, "Ledger")["project_id"]
    payments = make(signed_out, "Payments")["department_id"]
    signed_out.post_json(f"/api/departments/{payments}/projects", {"project_id": billing})

    in_billing = owner.in_project(billing).call("tree")
    in_ledger = owner.in_project(ledger).call("tree")

    assert in_billing["department"] == {"department_id": payments, "name": "Payments"}
    assert in_ledger["department"] is None


def test_the_contract_describes_every_department_call(console: Console, signed_out: ConsoleClient) -> None:
    document = signed_out.get("/api/openapi.json").json()

    operations = {op["operationId"] for path in document["paths"].values() for op in path.values()}

    assert {
        "departments",
        "create_department",
        "rename_department",
        "remove_department",
        "appoint_department_lead",
        "remove_department_lead",
        "move_project_in",
        "move_project_out",
    } <= operations
    assert "department" in document["components"]["schemas"]["ProjectDetail"]["properties"]
