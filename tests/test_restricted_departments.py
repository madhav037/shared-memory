"""Restricted departments (#633, ADR-0032 extending ADR-0006): a department lead closes their department to an access
list, and its department memory and its projects are invisible to every member outside it.

The boundary holds the way a restricted project's does, with the same single refusal, in every session tool, the hooks
and the console. A project inside a restricted department can be restricted further, but never reached from outside
the department, and never opened to the whole company. Admins reach everything. Sessions are driven over HTTP and the
console through its JSON API, both on the console's server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from tests.support import (
    Console,
    ConsoleClient,
    Session,
    add,
    added_context,
    ask,
    create,
    signed_in,
    signed_in_owner,
)

REVIEWS = {
    "title": "Treasury reviews",
    "summary": "Every treasury change needs two reviewers.",
    "type": "convention",
    "body": "SECRET-DEPARTMENT: every treasury change needs two approving reviewers before it merges.",
}
LEDGER = {
    "title": "Ledger closes at midnight",
    "summary": "The ledger closes at midnight UTC.",
    "type": "gotcha",
    "body": "SECRET-PROJECT: the ledger closes at midnight UTC and refuses late postings.",
}


@dataclass
class ARestrictedDepartment:
    """A company with a restricted department, Treasury, holding the project Billing with memory of its own; a project
    in no department, Payments; and Dana, a member outside Treasury."""

    owner: Session
    treasury: str
    billing: str
    payments: str
    department_memory: str
    project_memory: str
    dana: Session


def promoted(session: Session, memory: dict[str, str], level: str) -> str:
    personal = session.call("remember", **memory)["path"]
    done = session.call("promote", path=personal, level=level)
    if done["status"] == "similar_memories":
        done = session.call(
            "promote",
            path=personal,
            level=level,
            reference=done["reference"],
            resolutions={one["path"]: "keep_both" for one in done["similar"]},
        )
    assert done["status"] == "promoted", done
    path: str = done["path"]
    return path


def department(client: ConsoleClient, name: str, *projects: str) -> str:
    made = client.post_json("/api/departments", {"name": name})
    assert made.status_code == 200, made.text
    department_id: str = next(one for one in made.json()["departments"] if one["name"] == name)["department_id"]
    for project in projects:
        moved = client.post_json(f"/api/departments/{department_id}/projects", {"project_id": project})
        assert moved.status_code == 200, moved.text
    return department_id


def restrict(client: ConsoleClient, department_id: str, restricted: bool = True) -> httpx.Response:
    return client.post_json(f"/api/departments/{department_id}/restrict", {"restricted": restricted})


def restricted(console: Console, client: ConsoleClient, github: str, account: int) -> ARestrictedDepartment:
    owner = signed_in_owner(console, client, github, account)
    billing = create(client, "Billing")["project_id"]
    payments = create(client, "Payments")["project_id"]
    treasury = department(client, "Treasury", billing)
    appointed = client.post_json(f"/api/departments/{treasury}/leads", {"member_id": "E1001"})  # promotes into it
    assert appointed.status_code == 200, appointed.text
    in_billing = owner.in_project(billing, "billing-api")
    department_memory = promoted(in_billing, REVIEWS, "department")
    project_memory = promoted(in_billing, LEDGER, "project")
    in_billing.call("pin", path=department_memory)
    in_billing.call("pin", path=project_memory)
    dana = Session(console.server, add(client, "emp-2", "Dana Dev", f"dana-{github}")["personal_token"])
    closed = restrict(client, treasury)
    assert closed.status_code == 200, closed.text
    return ARestrictedDepartment(owner, treasury, billing, payments, department_memory, project_memory, dana)


def the(department_id: str, client: ConsoleClient) -> dict[str, Any]:
    listed = ask(client, "/api/departments")["departments"]
    found: dict[str, Any] = next(one for one in listed if one["department_id"] == department_id)
    return found


def test_a_department_lead_restricts_their_department_and_manages_its_access_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-closed-dept-one", 2701)
    treasury = department(signed_out, "Treasury")
    add(signed_out, "emp-3", "Lena Lead", "lena-closed-dept-one")
    add(signed_out, "emp-4", "Ivy Inside", "ivy-closed-dept-one")
    signed_out.post_json(f"/api/departments/{treasury}/leads", {"member_id": "emp-3"})
    lena = signed_in(console, "lena-closed-dept-one", 2702)

    closed = restrict(lena, treasury)
    let_in = lena.post_json(f"/api/departments/{treasury}/access", {"member_id": "emp-4"})
    taken_off = lena.post(f"/api/departments/{treasury}/access/emp-4/remove")

    assert closed.status_code == 200, closed.text
    as_closed = next(one for one in closed.json()["departments"] if one["department_id"] == treasury)
    assert as_closed["restricted"] is True
    assert as_closed["access"] == []
    with_ivy = next(one for one in let_in.json()["departments"] if one["department_id"] == treasury)
    assert [one["member_id"] for one in with_ivy["access"]] == ["emp-4"]
    without = next(one for one in taken_off.json()["departments"] if one["department_id"] == treasury)
    assert without["access"] == []
    lena.close()


def test_a_member_who_does_not_lead_the_department_cannot_restrict_it_or_change_its_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-closed-dept-two", 2703)
    treasury = department(signed_out, "Treasury")
    add(signed_out, "emp-2", "Dana Dev", "dana-closed-dept-two")
    dana = signed_in(console, "dana-closed-dept-two", 2704)

    closing = restrict(dana, treasury)
    letting_in = dana.post_json(f"/api/departments/{treasury}/access", {"member_id": "emp-2"})

    assert closing.status_code == 403
    assert "department's leads and the company's admins" in closing.json()["message"]
    assert letting_in.status_code == 403
    assert the(treasury, signed_out)["restricted"] is False
    dana.close()


def test_an_outsider_gets_the_restricted_refusal_for_its_projects_in_every_tool(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-three", 2705)
    in_billing = it.dana.in_project(it.billing, "billing-api")

    refusals = [
        in_billing.refusal("tree"),
        in_billing.refusal("search", query="ledger"),
        in_billing.refusal("remember", title="A note", summary="A note.", type="gotcha", body="A note."),
    ]
    started = in_billing.start()
    prompted = in_billing.prompt("when does the ledger close")

    assert all("is restricted" in refusal for refusal in refusals), refusals
    assert "hookSpecificOutput" not in started
    assert "is restricted" in started["systemMessage"]
    assert prompted == {}


def test_an_outsider_cant_reach_its_memory_by_path_from_another_project_nor_see_it_listed(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-four", 2706)
    from_payments = it.dana.in_project(it.payments, "payments-api")
    from_payments.call("remember", title="Refunds settle late", summary="Refunds.", type="gotcha", body="Five days.")

    refusals = {
        "read department memory": from_payments.refusal("read", path=it.department_memory),
        "read project memory": from_payments.refusal("read", path=it.project_memory),
        "list department memory": from_payments.refusal("list", folder=f"departments/{it.treasury}"),
        "pin": from_payments.refusal("pin", path=it.department_memory),
        "retire": from_payments.refusal("retire", path=it.department_memory),
    }
    departments = from_payments.call("list", folder="departments")
    projects = from_payments.call("list", folder="projects")
    found = from_payments.call("search", query="treasury reviewers ledger midnight")

    assert all("is restricted" in refusal for refusal in refusals.values()), refusals
    assert f"departments/{it.treasury}" not in departments["folders"]
    assert f"projects/{it.billing}" not in projects["folders"]
    assert f"projects/{it.payments}" in projects["folders"]
    assert "SECRET" not in str(found)


def test_an_outsider_promoting_to_company_isnt_shown_its_memory_as_similar(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-fourteen", 2719)
    from_payments = it.dana.in_project(it.payments, "payments-api")
    personal = from_payments.call("remember", **REVIEWS)["path"]

    done = from_payments.call("promote", path=personal, level="company")

    assert it.department_memory not in str(done), done
    assert it.project_memory not in str(done), done
    assert f"departments/{it.treasury}" not in str(done), done


def test_an_outsider_never_sees_it_in_the_console(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-five", 2707)
    dana = signed_in(console, "dana-olive-closed-dept-five", 2708)

    listed = ask(dana, "/api/departments")["departments"]
    projects = [one["project_id"] for one in ask(dana, "/api/projects")["projects"]]
    top = [folder["path"] for folder in ask(dana, "/api/files", folder="")["folders"]]
    searched = ask(dana, "/api/search", query="treasury reviewers ledger midnight")
    refused = [
        dana.get(f"/api/files?folder=departments/{it.treasury}"),
        dana.get(f"/api/files?folder=projects/{it.billing}"),
        dana.get(f"/api/memory?path={it.department_memory}"),
        dana.get(f"/api/memory/history?path={it.department_memory}"),
        dana.post_json("/api/memory/pin", {"path": it.department_memory}),
        dana.post_json("/api/memory/retire", {"path": it.department_memory}),
        dana.get(f"/api/projects/{it.billing}"),
    ]

    assert listed == []
    assert projects == [it.payments]
    assert f"departments/{it.treasury}" not in top
    assert f"projects/{it.billing}" not in top
    assert "SECRET" not in str(searched)
    assert [answer.status_code for answer in refused] == [403] * len(refused)
    assert all("is restricted" in answer.json()["message"] for answer in refused)
    assert not any("SECRET" in answer.text for answer in refused)
    dana.close()


def test_a_member_on_the_departments_list_reaches_its_memory_and_projects(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-six", 2709)
    signed_out.post_json(f"/api/departments/{it.treasury}/access", {"member_id": "emp-2"})
    in_billing = it.dana.in_project(it.billing, "billing-api")

    started = in_billing.start()
    read = in_billing.call("read", path=it.department_memory)
    dana = signed_in(console, "dana-olive-closed-dept-six", 2710)

    assert "Treasury reviews" in added_context(started)
    assert "Ledger closes at midnight" in added_context(started)
    assert "SECRET-DEPARTMENT" in read["body"]
    assert [one["department_id"] for one in ask(dana, "/api/departments")["departments"]] == [it.treasury]
    dana.close()


def test_a_member_on_the_departments_list_but_not_an_inner_projects_list_cant_reach_that_project(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-seven", 2711)
    ledger = create(signed_out, "Ledger")["project_id"]
    signed_out.post_json(f"/api/departments/{it.treasury}/projects", {"project_id": ledger})
    signed_out.post_json(f"/api/departments/{it.treasury}/access", {"member_id": "emp-2"})
    further = signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": True})

    in_billing = it.dana.in_project(it.billing, "billing-api").refusal("tree")
    from_ledger = it.dana.in_project(ledger, "ledger-api")

    assert further.status_code == 200, further.text
    assert "is restricted" in in_billing
    assert "is restricted" in from_ledger.refusal("read", path=it.project_memory)
    assert "SECRET-DEPARTMENT" in from_ledger.call("read", path=it.department_memory)["body"]


def test_a_member_on_an_inner_projects_list_but_outside_the_department_cant_reach_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-eight", 2712)
    signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": True})
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"member_id": "emp-2"})
    signed_out.post_json(f"/api/projects/{it.billing}/leads", {"member_id": "emp-2"})

    refused = it.dana.in_project(it.billing, "billing-api").refusal("tree")

    assert "is restricted" in refused


def test_opening_a_project_inside_a_restricted_department_to_the_whole_company_is_refused(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-nine", 2713)
    signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": True})

    opening = signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": False})

    assert opening.status_code == 403
    assert "restricted department" in opening.json()["message"]
    assert signed_out.get(f"/api/projects/{it.billing}").json()["restricted"] is True
    assert "is restricted" in it.dana.in_project(it.billing, "billing-api").refusal("tree")


def test_admins_reach_everything(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-ten", 2714)
    signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": True})
    made_admin = signed_out.post_json("/api/members/emp-2/admin", {"admin": True})
    in_billing = it.dana.in_project(it.billing, "billing-api")
    dana = signed_in(console, "dana-olive-closed-dept-ten", 2715)

    read = in_billing.call("read", path=it.department_memory)
    started = in_billing.start()
    listed = [one["department_id"] for one in ask(dana, "/api/departments")["departments"]]
    projects = [one["project_id"] for one in ask(dana, "/api/projects")["projects"]]

    assert made_admin.status_code == 200, made_admin.text
    assert "SECRET-DEPARTMENT" in read["body"]
    assert "Treasury reviews" in added_context(started)
    assert listed == [it.treasury]
    assert it.billing in projects
    assert dana.get(f"/api/memory?path={it.department_memory}").status_code == 200
    dana.close()


def test_losing_the_department_takes_effect_on_the_next_call(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-eleven", 2716)
    signed_out.post_json(f"/api/departments/{it.treasury}/access", {"member_id": "emp-2"})
    while_allowed = it.dana.in_project(it.billing, "billing-api").call("read", path=it.department_memory)

    signed_out.post(f"/api/departments/{it.treasury}/access/emp-2/remove")
    after = it.dana.in_project(it.billing, "billing-api").refusal("tree")

    assert "SECRET-DEPARTMENT" in while_allowed["body"]
    assert "is restricted" in after


def test_moving_a_project_into_a_restricted_department_hides_it_from_outsiders(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-twelve", 2717)
    before = it.dana.in_project(it.payments, "payments-api").call("tree")

    signed_out.post_json(f"/api/departments/{it.treasury}/projects", {"project_id": it.payments})
    after = it.dana.in_project(it.payments, "payments-api").refusal("tree")

    assert "folders" in before
    assert "is restricted" in after


def test_every_change_to_a_departments_access_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-dept-thirteen", 2718)

    signed_out.post_json(f"/api/departments/{it.treasury}/access", {"member_id": "emp-2"})
    signed_out.post(f"/api/departments/{it.treasury}/access/emp-2/remove")
    restrict(signed_out, it.treasury, restricted=False)

    log = [
        event
        for event in ask(signed_out, "/api/audit")["events"]
        if event["target"] == it.treasury and event["kind"].startswith("department_")
        and event["kind"] not in ("department_created", "department_lead_appointed")
    ]
    assert [event["kind"] for event in log] == [
        "department_opened",
        "department_access_revoked",
        "department_access_granted",
        "department_restricted",
    ]
    assert [event["detail"].get("member_id") for event in log][1:3] == ["emp-2", "emp-2"]
