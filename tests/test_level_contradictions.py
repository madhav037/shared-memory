"""Level contradictions, upward (#634): a narrower memory promoted against a broader one.

A promotion whose session judges that a project memory contradicts department or company memory, or a department memory
contradicts company memory, makes the narrower memory an exception to the broader one. When the member promoting it
doesn't lead the narrower level, it is a level contradiction raised to that level's leads (the project's leads, or the
department's). Until they decide, the narrower memory holds where it applies. Keeping an exception records a reason;
following retires the narrower memory. A lead's own promotion is settled at once, as a project-over-company exception
always was. Sessions are driven over HTTP and the console through its JSON API, both on the console's server.
"""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, add, added_context, ask, create, signed_in_owner
from tests.test_department_memory import department

JSON_LOGS = {
    "title": "Log in JSON",
    "summary": "All services log JSON.",
    "type": "convention",
    "body": "Every service writes structured JSON logs to stdout.",
}
PLAIN_LOGS = {
    "title": "Billing logs plain text",
    "summary": "The billing service logs plain text.",
    "type": "convention",
    "body": "The old billing service writes plain text logs to stdout, not JSON.",
}
REASON = "The billing service's log shipper reads plain text only until it is replaced next year."
HEADING = "[level contradictions waiting for your decision]"


def member(console: Console, client: ConsoleClient, member_id: str, name: str, project: str) -> Session:
    return Session(console.server, add(client, member_id, name)["personal_token"], project, "app")


def promoted_now(session: Session, memory: dict[str, str], level: str) -> str:
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level=level)
    if first["status"] == "similar_memories":
        first = session.call(
            "promote", path=personal, level=level, reference=first["reference"],
            resolutions={one["path"]: "keep_both" for one in first["similar"]},
        )  # fmt: skip
    assert first["status"] == "promoted", first
    return str(first["path"])


def contradicting(session: Session, memory: dict[str, str], broader: str, level: str = "project") -> dict[str, Any]:
    """Promote a memory the session judges contradicts `broader`: it resolves `broader` with supersede."""
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level=level)
    assert first["status"] == "similar_memories", first
    assert broader in [one["path"] for one in first["similar"]]
    resolutions = {one["path"]: "supersede" if one["path"] == broader else "keep_both" for one in first["similar"]}
    answer: dict[str, Any] = session.call(
        "promote", path=personal, level=level, reference=first["reference"], resolutions=resolutions
    )
    return answer


def a_project_contradiction(console: Console, client: ConsoleClient, github: str, account: int) -> dict[str, Any]:
    """Olive, the owner, leads Billing and Checkout; Dana, who leads neither, promotes a Billing memory contradicting
    company memory."""
    owner = signed_in_owner(console, client, github, account)
    billing = create(client, "Billing")["project_id"]
    checkout = create(client, "Checkout")["project_id"]
    olive = owner.in_project(billing)
    company = promoted_now(olive, JSON_LOGS, "company")
    dana = member(console, client, "emp-dana", "Dana Developer", billing)
    raised = contradicting(dana, PLAIN_LOGS, company)
    return {"olive": olive, "dana": dana, "company": company, "raised": raised, "checkout": owner.in_project(checkout)}


def test_promoting_a_project_memory_against_company_memory_raises_a_level_contradiction_to_the_projects_leads(
    console: Console, signed_out: ConsoleClient
) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-one", 6341)
    raised, company = made["raised"], made["company"]

    assert raised["status"] == "promoted", raised
    assert "level_contradiction" in raised
    narrower = made["dana"].call("read", path=raised["path"])
    assert (narrower["level"], narrower["exception_to"]) == ("project", company)
    briefed = added_context(made["olive"].start())
    assert HEADING in briefed
    assert f"Level contradiction {raised['level_contradiction']}, waiting today" in briefed
    assert "Billing logs plain text" in briefed and "Log in JSON" in briefed
    assert HEADING not in added_context(made["dana"].start())
    events = [e for e in ask(signed_out, "/api/audit")["events"] if e["kind"] == "challenge_raised"]
    assert events[0]["detail"]["challenge"] == "level_contradiction"


def test_a_waiting_level_contradiction_shows_its_age_in_the_leads_briefing(
    console: Console, signed_out: ConsoleClient
) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-age", 6342)
    console.clock.advance(days=3)

    briefed = added_context(made["olive"].start())

    assert f"Level contradiction {made['raised']['level_contradiction']}, waiting 3 days" in briefed


def test_while_it_waits_sessions_in_the_project_receive_the_narrower_memory_and_others_the_broader(
    console: Console, signed_out: ConsoleClient
) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-two", 6343)
    narrower, company = made["raised"]["path"], made["company"]
    made["olive"].call("pin", path=company)

    in_billing = added_context(made["dana"].prompt("how does the billing service write its logs?"))

    assert narrower in in_billing
    assert company not in in_billing
    assert "structured JSON logs" not in added_context(made["dana"].start())
    assert "structured JSON logs" in added_context(made["checkout"].start())
    assert company in added_context(made["checkout"].prompt("how should services write their logs?"))


def test_a_department_memory_against_company_memory_raises_a_level_contradiction_to_the_department_leads(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-level-three", 6344)
    billing = create(signed_out, "Billing")["project_id"]
    lena = member(console, signed_out, "emp-lena", "Lena Lead", billing)
    payments = department(signed_out, "Payments", billing, lead="emp-lena")
    company = promoted_now(owner.in_project(billing), JSON_LOGS, "company")
    dana = member(console, signed_out, "emp-dana", "Dana Developer", billing)

    asked = contradicting(dana, PLAIN_LOGS, company, level="department")
    assert asked["status"] == "challenge_raised", asked
    accepted = lena.call("decide_challenge", challenge_id=asked["challenge_id"], decision="accept")

    assert accepted["path"].startswith(f"departments/{payments}/")
    moved = lena.call("read", path=accepted["path"])
    assert (moved["level"], moved["exception_to"]) == ("department", company)
    briefed = added_context(lena.start())
    assert HEADING in briefed
    assert "department memory" in briefed
    assert HEADING not in added_context(owner.in_project(billing).start())


def test_a_department_leads_own_promotion_against_company_memory_is_an_exception_at_once(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-level-four", 6345)
    billing = create(signed_out, "Billing")["project_id"]
    olive = owner.in_project(billing)
    department(signed_out, "Payments", billing)
    company = promoted_now(olive, JSON_LOGS, "company")

    answer = contradicting(olive, PLAIN_LOGS, company, level="department")

    assert answer["status"] == "promoted" and "level_contradiction" not in answer, answer
    assert olive.call("read", path=answer["path"])["exception_to"] == company
    assert HEADING not in added_context(olive.start())


def test_keeping_an_exception_from_a_session_records_its_reason_and_the_narrower_memory_still_holds(
    console: Console, signed_out: ConsoleClient
) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-five", 6346)
    narrower, company = made["raised"]["path"], made["company"]
    olive = made["olive"]

    kept = olive.call(
        "decide_challenge", challenge_id=made["raised"]["level_contradiction"], decision="keep_exception", reason=REASON
    )

    assert kept["status"] == "kept_exception", kept
    read = olive.call("read", path=narrower)
    assert (read["status"], read["exception_to"], read["exception_reason"]) == ("active", company, REASON)
    assert HEADING not in added_context(olive.start())
    in_billing = added_context(made["dana"].prompt("how does the billing service write its logs?"))
    assert narrower in in_billing and company not in in_billing
    decided = [e for e in ask(signed_out, "/api/audit")["events"] if e["kind"] == "challenge_decided"]
    assert decided[0]["detail"]["decision"] == "kept_exception"


def test_keeping_an_exception_needs_a_reason(console: Console, signed_out: ConsoleClient) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-six", 6347)

    refused = made["olive"].refusal(
        "decide_challenge", challenge_id=made["raised"]["level_contradiction"], decision="keep_exception"
    )

    assert "reason" in refused


def test_following_from_a_session_retires_the_narrower_memory_and_sessions_receive_the_broader(
    console: Console, signed_out: ConsoleClient
) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-seven", 6348)
    narrower, company = made["raised"]["path"], made["company"]

    followed = made["olive"].call("decide_challenge", challenge_id=made["raised"]["level_contradiction"], decision="follow")

    assert followed["status"] == "followed", followed
    assert made["olive"].call("read", path=narrower)["status"] == "retired"
    assert company in added_context(made["dana"].prompt("how should services write their logs?"))
    assert f"level contradiction {made['raised']['level_contradiction']}" in added_context(made["dana"].start())


def test_only_the_narrower_levels_lead_decides_a_level_contradiction(console: Console, signed_out: ConsoleClient) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-eight", 6349)
    contradiction = made["raised"]["level_contradiction"]

    assert "lead" in made["dana"].refusal("decide_challenge", challenge_id=contradiction, decision="follow")
    assert "keep_exception" in made["olive"].refusal("decide_challenge", challenge_id=contradiction, decision="accept")


def test_a_project_leads_own_exception_to_company_memory_behaves_as_before(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-level-nine", 6350)
    billing = create(signed_out, "Billing")["project_id"]
    olive = owner.in_project(billing)
    company = promoted_now(olive, JSON_LOGS, "company")

    answer = contradicting(olive, PLAIN_LOGS, company)

    assert answer["status"] == "promoted" and "level_contradiction" not in answer, answer
    exception = olive.call("read", path=answer["path"])
    assert (exception["level"], exception["exception_to"]) == ("project", company)
    assert olive.call("read", path=company)["status"] == "active"
    assert HEADING not in added_context(olive.start())
    assert f"exception to {company}" in added_context(olive.prompt("how does the billing service write its logs?"))


# The console's JSON API


def test_the_console_shows_a_level_contradiction_beside_both_memories_with_their_levels(
    console: Console, signed_out: ConsoleClient
) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-ten", 6351)

    [waiting] = ask(signed_out, "/api/challenges")["waiting"]

    assert waiting["kind"] == "level_contradiction"
    assert waiting["decides_as"] == "lead"
    assert (waiting["target"]["path"], waiting["target"]["level"]) == (made["company"], "company")
    assert (waiting["challenger"]["path"], waiting["challenger"]["level"]) == (made["raised"]["path"], "project")


def test_the_console_keeps_an_exception_with_a_reason(console: Console, signed_out: ConsoleClient) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-eleven", 6352)
    contradiction = made["raised"]["level_contradiction"]

    without = signed_out.post_json(f"/api/challenges/{contradiction}/decide", {"decision": "keep_exception"})
    kept = signed_out.post_json(
        f"/api/challenges/{contradiction}/decide", {"decision": "keep_exception", "reason": REASON}
    )

    assert without.status_code == 403 and "reason" in without.json()["message"]
    assert kept.status_code == 200, kept.text
    assert kept.json()["decided"] == {
        "challenge_id": contradiction, "decision": "kept_exception", "in_force": made["raised"]["path"],
    }  # fmt: skip
    assert kept.json()["waiting"] == []
    assert made["olive"].call("read", path=made["raised"]["path"])["exception_reason"] == REASON


def test_the_console_follows_by_retiring_the_narrower_memory(console: Console, signed_out: ConsoleClient) -> None:
    made = a_project_contradiction(console, signed_out, "olive-level-twelve", 6353)
    contradiction = made["raised"]["level_contradiction"]

    followed = signed_out.post_json(f"/api/challenges/{contradiction}/decide", {"decision": "follow"})

    assert followed.status_code == 200, followed.text
    assert followed.json()["decided"] == {
        "challenge_id": contradiction, "decision": "followed", "in_force": made["company"],
    }  # fmt: skip
    assert made["olive"].call("read", path=made["raised"]["path"])["status"] == "retired"
