"""A promotion into department memory by anyone but a department lead is a challenge to the leads (#632, ADR-0033).

The memory stays the member's personal memory until a lead decides: accepting moves it into department memory in its
author's name, refusing leaves it personal. A department with no lead left is decided by the company's admins.
Sessions are driven over HTTP and the console through its JSON API, both on the console's server.
"""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, add, added_context, ask, create, signed_in_owner
from tests.test_department_memory import REVIEWS, department, promoted

REASONING = "Every project in payments merges money code; one reviewer has missed rounding bugs twice."


def ask_leads(session: Session, memory: dict[str, str] = REVIEWS) -> tuple[str, dict[str, Any]]:
    """A non-lead's promotion into department memory, keeping both of anything similar: its personal path and what
    promote answered."""
    personal: str = session.call("remember", **memory)["path"]
    answered = session.call("promote", path=personal, level="department", reasoning=REASONING)
    if answered["status"] == "similar_memories":
        answered = session.call(
            "promote",
            path=personal,
            level="department",
            reference=answered["reference"],
            resolutions={one["path"]: "keep_both" for one in answered["similar"]},
            reasoning=REASONING,
        )
    return personal, answered


def member(console: Console, client: ConsoleClient, member_id: str, name: str, project: str) -> Session:
    return Session(console.server, add(client, member_id, name)["personal_token"], project, "app")


def test_a_non_leads_promotion_to_department_level_raises_a_challenge_to_the_department_leads_and_stays_personal(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-challenge-one", 1921)
    billing = create(signed_out, "Billing")["project_id"]
    member(console, signed_out, "emp-lena", "Lena Lead", billing)
    payments = department(signed_out, "Payments", billing, lead="emp-lena")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)

    personal, answered = ask_leads(dana)

    assert answered["status"] == "challenge_raised", answered
    assert answered["challenges"] == f"departments/{payments}"
    assert "department lead" in answered["next"]
    assert dana.call("read", path=personal)["level"] == "personal"
    assert owner.in_project(billing).call("tree", level="department")["folders"] == []
    raised = [e for e in ask(signed_out, "/api/audit")["events"] if e["kind"] == "challenge_raised"]
    assert raised[0]["detail"]["challenge"] == "promote"
    assert "waiting on challenge" in dana.refusal("promote", path=personal, level="department")


def test_a_leads_briefing_shows_the_waiting_challenge_with_the_members_reasoning(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-dept-challenge-two", 1922)
    billing = create(signed_out, "Billing")["project_id"]
    lena = member(console, signed_out, "emp-lena", "Lena Lead", billing)
    department(signed_out, "Payments", billing, lead="emp-lena")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)
    _, answered = ask_leads(dana)

    briefed = added_context(lena.start())

    assert "[department challenges waiting for your decision]" in briefed
    assert f"Challenge {answered['challenge_id']} by emp-dana, yours to decide as a department lead" in briefed
    assert "Two reviewers on every change" in briefed
    assert REASONING in briefed
    assert "department challenges" not in added_context(dana.start())


def test_a_memory_waiting_on_a_department_challenge_cannot_change_so_the_lead_accepts_what_was_offered(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-dept-challenge-offered", 1929)
    billing = create(signed_out, "Billing")["project_id"]
    lena = member(console, signed_out, "emp-lena", "Lena Lead", billing)
    department(signed_out, "Payments", billing, lead="emp-lena")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)
    personal, answered = ask_leads(dana)

    edited = dana.refusal("edit_memory", path=personal, body="Push straight to main.")
    deleted = dana.refusal("delete_memory", path=personal)
    accepted = lena.call("decide_challenge", challenge_id=answered["challenge_id"], decision="accept")

    assert f"waiting on challenge {answered['challenge_id']}" in edited
    assert f"waiting on challenge {answered['challenge_id']}" in deleted
    assert lena.call("read", path=accepted["path"])["body"] == REVIEWS["body"]


def test_a_lead_accepting_the_challenge_moves_the_memory_into_department_memory(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-dept-challenge-three", 1923)
    billing = create(signed_out, "Billing")["project_id"]
    lena = member(console, signed_out, "emp-lena", "Lena Lead", billing)
    payments = department(signed_out, "Payments", billing, lead="emp-lena")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)
    personal, answered = ask_leads(dana)

    accepted = lena.call("decide_challenge", challenge_id=answered["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted"
    assert accepted["path"].startswith(f"departments/{payments}/conventions/")
    moved = lena.call("read", path=accepted["path"])
    assert moved["level"] == "department"
    assert moved["author"] == "emp-dana"
    assert dana.refusal("read", path=personal)
    assert accepted["path"] in added_context(dana.start())  # Dana is told it is now department memory
    decided = [e for e in ask(signed_out, "/api/audit")["events"] if e["kind"] == "challenge_decided"]
    assert decided[0]["detail"]["decided_as"] == "department_lead"


def test_accepting_a_leads_challenge_to_another_authors_department_memory_keeps_it_department_memory(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-dept-challenge-eight", 1928)
    billing = create(signed_out, "Billing")["project_id"]
    lena = member(console, signed_out, "emp-lena", "Lena Lead", billing)
    mira = member(console, signed_out, "emp-mira", "Mira Lead", billing)
    payments = department(signed_out, "Payments", billing, lead="emp-lena")
    appointed = signed_out.post_json(f"/api/departments/{payments}/leads", {"member_id": "emp-mira"})
    assert appointed.status_code == 200, appointed.text
    target = promoted(lena, REVIEWS, "department")
    personal = mira.call("remember", **REVIEWS)["path"]
    first = mira.call("promote", path=personal, level="department")
    assert first["status"] == "similar_memories", first
    raised = mira.call(
        "promote",
        path=personal,
        level="department",
        reference=first["reference"],
        resolutions={one["path"]: ("supersede" if one["path"] == target else "keep_both") for one in first["similar"]},
    )
    assert raised["status"] == "challenge_raised", raised

    accepted = lena.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted", accepted
    assert accepted["path"].startswith(f"departments/{payments}/conventions/"), accepted
    new = lena.call("read", path=accepted["path"])
    assert (new["level"], new["author"], new["replaces"]) == ("department", "emp-mira", target)
    assert lena.call("read", path=target)["status"] == "superseded"


def test_a_lead_refusing_the_challenge_leaves_the_memory_personal(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-challenge-four", 1924)
    billing = create(signed_out, "Billing")["project_id"]
    lena = member(console, signed_out, "emp-lena", "Lena Lead", billing)
    department(signed_out, "Payments", billing, lead="emp-lena")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)
    personal, answered = ask_leads(dana)

    refused = lena.call("decide_challenge", challenge_id=answered["challenge_id"], decision="reject")

    assert refused["status"] == "rejected"
    assert dana.call("read", path=personal)["level"] == "personal"
    assert owner.in_project(billing).call("tree", level="department")["folders"] == []
    assert f"Your challenge {answered['challenge_id']}" in added_context(dana.start())


def test_only_a_department_lead_decides_while_the_department_has_one(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-challenge-five", 1925)
    billing = create(signed_out, "Billing")["project_id"]
    member(console, signed_out, "emp-lena", "Lena Lead", billing)
    department(signed_out, "Payments", billing, lead="emp-lena")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)
    _, answered = ask_leads(dana)

    by_admin = owner.in_project(billing).refusal("decide_challenge", challenge_id=answered["challenge_id"], decision="accept")
    by_author = dana.refusal("decide_challenge", challenge_id=answered["challenge_id"], decision="accept")

    assert "department lead" in by_admin
    assert "department lead" in by_author


def test_with_no_department_lead_the_challenge_goes_to_admins_and_an_admin_decides_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-challenge-six", 1926)
    billing = create(signed_out, "Billing")["project_id"]
    payments = department(signed_out, "Payments", billing, lead=None)
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)
    _, answered = ask_leads(dana)
    admin = owner.in_project(billing)

    briefed = added_context(admin.start())
    accepted = admin.call("decide_challenge", challenge_id=answered["challenge_id"], decision="accept")

    assert f"Challenge {answered['challenge_id']} by emp-dana, yours to decide as an admin" in briefed
    assert accepted["path"].startswith(f"departments/{payments}/")
    decided = [e for e in ask(signed_out, "/api/audit")["events"] if e["kind"] == "challenge_decided"]
    assert decided[0]["detail"]["decided_as"] == "admin"


def test_the_console_challenges_screen_lists_and_decides_a_department_challenge(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-dept-challenge-seven", 1927)
    billing = create(signed_out, "Billing")["project_id"]
    payments = department(signed_out, "Payments", billing, lead="E1001")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)
    personal, answered = ask_leads(dana)

    listed = ask(signed_out, "/api/challenges")["waiting"]
    decided = signed_out.post_json(f"/api/challenges/{answered['challenge_id']}/decide", {"decision": "accept"})

    shown = next(one for one in listed if one["challenge_id"] == answered["challenge_id"])
    assert shown["kind"] == "promote"
    assert shown["decides_as"] == "department_lead"
    assert shown["reasoning"] == REASONING
    assert shown["target"]["path"] == f"departments/{payments}"
    assert shown["target"]["title"] == "Payments"
    assert shown["target"]["level"] == "department"
    assert shown["challenger"]["path"] == personal
    assert decided.status_code == 200, decided.text
    in_force = decided.json()["decided"]["in_force"]
    assert in_force.startswith(f"departments/{payments}/")
    assert answered["challenge_id"] not in [one["challenge_id"] for one in decided.json()["waiting"]]
