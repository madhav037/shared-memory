"""What a member can't reach stays out of everything they are shown: a memory's history, the notices their sessions
and the console tell them, and the refusal of a pin over the briefing cap (ADR-0006, ADR-0032)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import (
    Console,
    ConsoleClient,
    Session,
    add,
    added_context,
    ask,
    challenge,
    create,
    promote_keeping_both,
    signed_in,
    signed_in_owner,
)


def restrict(client: ConsoleClient, project: str) -> None:
    closed = client.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    assert closed.status_code == 200, closed.text


def memory(title: str, body: str | None = None) -> dict[str, str]:
    return {"title": title, "summary": f"{title}.", "type": "convention", "body": body or f"{title}, every time."}


def a_member(console: Console, client: ConsoleClient, github: str) -> Session:
    return Session(console.server, add(client, "emp-2", "Dana Dev", github)["personal_token"])


def test_history_stops_where_a_memory_was_somewhere_the_member_cant_reach(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-unseen-one", 2101)
    billing = create(signed_out, "Billing")["project_id"]
    create(signed_out, "Payments")  # where Dana reads company memory from
    restrict(signed_out, billing)
    a_member(console, signed_out, "dana-unseen-one")
    in_billing = owner.in_project(billing, "billing-api")
    personal = in_billing.call("remember", **memory("Retries", "Drafted with HIDDEN-CLIENT-NAME."))["path"]
    in_billing.call("edit_memory", path=personal, body="Retry three times.")
    company = in_billing.call("promote", path=personal, level="company")["path"]
    everything = ask(signed_out, "/api/memory/history", path=company)["versions"]
    dana = signed_in(console, "dana-unseen-one", 2102)

    seen = ask(dana, "/api/memory/history", path=company)["versions"]
    hidden = dana.get(f"/api/memory/version?path={company}&commit={everything[-1]['commit']}")

    assert len(everything) == 3, "the owner, who reaches the project, still sees the whole trail"
    assert [one["commit"] for one in seen] == [everything[0]["commit"]]
    assert "Promote" in seen[0]["message"]
    assert hidden.status_code == 403
    assert "HIDDEN-CLIENT-NAME" not in hidden.text
    assert "HIDDEN-CLIENT-NAME" in ask(signed_out, "/api/memory/version", path=company, commit=everything[-1]["commit"])["text"]
    dana.close()


def test_an_author_shut_out_of_a_project_is_not_told_of_doubts_on_their_memory_there(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-unseen-two", 2103)
    billing, payments = create(signed_out, "Billing")["project_id"], create(signed_out, "Payments")["project_id"]
    dana = a_member(console, signed_out, "dana-unseen-two")
    path = promote_keeping_both(dana.in_project(billing, "billing-api"), memory("Acquisition plan"))
    restrict(signed_out, billing)

    owner.in_project(billing, "billing-api").call("challenge", path=path, reason="misled", reasoning="HIDDEN-REASONING")
    told = added_context(dana.in_project(payments, "payments-api").prompt("hello"))

    assert "HIDDEN-REASONING" not in told
    assert path not in told


def test_a_challenge_from_a_project_the_author_cant_reach_is_named_by_its_number_alone(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-unseen-three", 2104)
    billing, payments = create(signed_out, "Billing")["project_id"], create(signed_out, "Payments")["project_id"]
    dana = a_member(console, signed_out, "dana-unseen-three").in_project(payments, "payments-api")
    target = promote_keeping_both(dana, memory("Staging resets nightly", "The staging database is wiped every night."), "company")
    restrict(signed_out, billing)

    raised = challenge(
        owner.in_project(billing, "billing-api"),
        memory("Staging resets at 02:17 UTC", "The staging database is wiped at 02:17 UTC."),
        target,
        "company",
        reasoning="HIDDEN-REASONING",
    )
    told = added_context(dana.prompt("hello"))

    assert f"Challenge {raised['challenge_id']}" in told, "the author still learns their memory is challenged"
    assert "02:17" not in told
    assert "HIDDEN-REASONING" not in told
    assert billing not in told


def comments_after_restricting(
    console: Console, client: ConsoleClient, github: str, account: int
) -> tuple[str, Session, ConsoleClient]:
    """Dana's done card in Billing gets a comment while she still reaches Billing, then Billing is restricted with her
    off its access list, and it gets another."""
    owner = signed_in_owner(console, client, github, account)
    billing, payments = create(client, "Billing")["project_id"], create(client, "Payments")["project_id"]
    dana = a_member(console, client, f"dana-{github}")
    in_billing = dana.in_project(billing, "billing-api")
    number = in_billing.call("add_card", title="Ship it")["number"]
    in_billing.call("claim_card", number=number)
    in_billing.call("update_card", number=number, column="done")
    owner.in_project(billing, "billing-api").call("comment_card", number=number, text="HIDDEN-BEFORE")
    restrict(client, billing)
    owner.in_project(billing, "billing-api").call("comment_card", number=number, text="HIDDEN-AFTER")
    return billing, dana.in_project(payments, "payments-api"), signed_in(console, f"dana-{github}", account + 1)


def test_a_member_shut_out_of_a_project_is_told_nothing_about_its_cards(console: Console, signed_out: ConsoleClient) -> None:
    billing, dana, browser = comments_after_restricting(console, signed_out, "olive-unseen-four", 2105)

    in_console: list[dict[str, Any]] = ask(browser, "/api/notices")["notices"]
    told = added_context(dana.prompt("hello"))

    assert in_console == []
    assert "HIDDEN" not in told and billing not in told
    browser.close()


def test_what_a_member_was_not_told_reaches_them_once_they_are_let_back_in(
    console: Console, signed_out: ConsoleClient
) -> None:
    billing, dana, browser = comments_after_restricting(console, signed_out, "olive-unseen-five", 2107)
    added_context(dana.prompt("hello"))
    signed_out.post_json(f"/api/projects/{billing}/access", {"member_id": "emp-2"})

    told = added_context(dana.prompt("hello again"))

    assert "HIDDEN-BEFORE" in told and "HIDDEN-AFTER" in told
    browser.close()


def test_a_pin_over_the_cap_of_a_briefing_the_member_cant_see_names_none_of_its_pins(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-unseen-six", 2109)
    billing, payments = create(signed_out, "Billing")["project_id"], create(signed_out, "Payments")["project_id"]
    restrict(signed_out, billing)
    words = "Reconciliation chargebacks settlements subscriptions entitlements provisioning deprovisioning"
    hidden = promote_keeping_both(owner.in_project(billing, "billing-api"), memory("Acquire Acme", " ".join([words] * 40)))
    assert signed_out.post_json("/api/memory/pin", {"path": hidden}).status_code == 200
    handbook = promote_keeping_both(
        owner.in_project(payments, "payments-api"), memory("Company handbook", " ".join([words] * 40)), "company"
    )

    refused = a_member(console, signed_out, "dana-unseen-six").in_project(payments, "payments-api").refusal("pin", path=handbook)

    assert "over its cap" in refused
    assert "a briefing you can't see" in refused
    assert billing not in refused and hidden not in refused


def a_department(client: ConsoleClient, name: str, project: str) -> str:
    made = client.post_json("/api/departments", {"name": name})
    assert made.status_code == 200, made.text
    department: str = next(one["department_id"] for one in made.json()["departments"] if one["name"] == name)
    assert client.post_json(f"/api/departments/{department}/projects", {"project_id": project}).status_code == 200
    assert client.post_json(f"/api/departments/{department}/leads", {"member_id": "E1001"}).status_code == 200
    return department


@pytest.mark.parametrize("level", ["project", "department"])
def test_news_of_a_challenge_about_memory_the_member_cant_reach_waits_until_they_can(
    console: Console, signed_out: ConsoleClient, level: str
) -> None:
    owner = signed_in_owner(console, signed_out, f"olive-unseen-{level}", 2111 if level == "project" else 2113)
    billing, payments = create(signed_out, "Billing")["project_id"], create(signed_out, "Payments")["project_id"]
    department = a_department(signed_out, "Treasury", billing) if level == "department" else None
    path = promote_keeping_both(owner.in_project(billing, "billing-api"), memory("Ledger closes at midnight"), level)
    dana = a_member(console, signed_out, f"dana-unseen-{level}").in_project(payments, "payments-api")
    raised = dana.call("challenge", path=path, reason="misled", reasoning="It closes at noon.")
    closed = f"/api/departments/{department}/restrict" if department else f"/api/projects/{billing}/restrict"
    assert signed_out.post_json(closed, {"restricted": True}).status_code == 200
    owner.in_project(billing, "billing-api").call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")
    browser = signed_in(console, f"dana-unseen-{level}", 2112 if level == "project" else 2114)

    in_console: list[dict[str, Any]] = ask(browser, "/api/notices")["notices"]
    told = added_context(dana.prompt("hello"))

    assert in_console == []
    assert path not in told and f"Your challenge {raised['challenge_id']}" not in told
    browser.close()
