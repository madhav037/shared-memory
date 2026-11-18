"""Doubts in the console (#539, spec #502): the challenge list carries a doubt's reason, its evidence and its +1
count; a memory read carries its in-doubt mark; deciding a doubt goes through the existing decide route. The console
only reads and decides them: only a session raises one (ADR-0009). Driven through the console's JSON API."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, add, ask, signed_in_owner

TAX = {
    "title": "Sales tax is fifteen percent",
    "summary": "Invoices add fifteen percent sales tax.",
    "type": "convention",
    "body": "Every invoice adds a flat fifteen percent sales tax on the subtotal.",
}
TAX_LINE = {"code_reference": "billing-api:src/tax.py:42", "quoted_line": "RATE = Decimal('0.20')"}
ROUNDING_LINE = {"code_reference": "billing-api:src/totals.py:7", "quoted_line": "return total.quantize(CENT)"}


def a_doubted_team(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session, Session]:
    """The owner signed in to the console with a project memory of theirs, and two members whose sessions doubt it."""
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    personal = in_project.call("remember", **TAX)["path"]
    path: str = in_project.call("promote", path=personal, level="project")["path"]
    dana = Session(console.server, add(client, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    ash = Session(console.server, add(client, "emp-3", "Ash Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    return path, dana, ash


def doubt(session: Session, path: str, reason: str, **extra: Any) -> int:
    challenge_id: int = session.call("challenge", path=path, reason=reason, **extra)["challenge_id"]
    return challenge_id


def waiting(client: ConsoleClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = ask(client, "/api/challenges")["waiting"]
    return found


def test_the_challenge_list_carries_a_doubts_reason_its_evidence_and_its_count(
    console: Console, signed_out: ConsoleClient
) -> None:
    path, dana, ash = a_doubted_team(console, signed_out, "olive-doubts-listed", 5401)
    challenge_id = doubt(dana, path, "contradicts_code", reasoning="The code charges twenty percent.", **TAX_LINE)
    doubt(ash, path, "contradicts_code", **ROUNDING_LINE)

    [listed] = waiting(signed_out)

    assert listed["challenge_id"] == challenge_id
    assert listed["kind"] == "doubt"
    assert listed["reason"] == "contradicts_code"
    assert listed["count"] == 2
    assert listed["target"]["path"] == path
    assert listed["challenger"] is None
    assert [
        {name: one[name] for name in ("member_id", "reasoning", "code_reference", "quoted_line")}
        for one in listed["evidence"]
    ] == [
        {"member_id": "emp-2", "reasoning": "The code charges twenty percent.", **TAX_LINE},
        {"member_id": "emp-3", "reasoning": None, **ROUNDING_LINE},
    ]
    assert all(one["raised_at"] for one in listed["evidence"])


def test_a_misled_doubt_carries_evidence_with_no_code_reference(console: Console, signed_out: ConsoleClient) -> None:
    path, dana, ash = a_doubted_team(console, signed_out, "olive-doubts-misled", 5402)
    doubt(dana, path, "misled", reasoning="Invoices came out wrong.")

    [listed] = waiting(signed_out)

    assert listed["reason"] == "misled"
    assert listed["count"] == 1
    assert [(one["member_id"], one["reasoning"], one["code_reference"]) for one in listed["evidence"]] == [
        ("emp-2", "Invoices came out wrong.", None)
    ]


def test_a_challenge_that_names_no_reason_has_no_evidence_and_no_count(
    console: Console, signed_out: ConsoleClient
) -> None:
    path, dana, ash = a_doubted_team(console, signed_out, "olive-doubts-none", 5403)
    # Retiring another author's memory from a session raises a retire challenge, which names no reason.
    dana.call("retire", path=path)

    [listed] = waiting(signed_out)

    assert listed["kind"] == "retire"
    assert listed["reason"] is None
    assert listed["evidence"] == []
    assert listed["count"] is None


def test_a_memory_read_in_the_console_carries_its_in_doubt_count_and_reasons(
    console: Console, signed_out: ConsoleClient
) -> None:
    path, dana, ash = a_doubted_team(console, signed_out, "olive-doubts-read", 5405)
    doubt(dana, path, "misled")
    doubt(ash, path, "misled")
    doubt(ash, path, "contradicts_code", **TAX_LINE)

    memory = ask(signed_out, "/api/memory", path=path)

    assert memory["in_doubt"] == {
        "count": 3,
        "reasons": [
            {"reason": "misled", "count": 2, "code_references": []},
            {"reason": "contradicts_code", "count": 1, "code_references": ["billing-api:src/tax.py:42"]},
        ],
    }
    assert sorted(one["reason"] for one in memory["open_challenges"]) == ["contradicts_code", "misled"]


def test_a_memory_no_one_doubts_is_not_in_doubt(console: Console, signed_out: ConsoleClient) -> None:
    path, dana, ash = a_doubted_team(console, signed_out, "olive-doubts-sound", 5406)

    memory = ask(signed_out, "/api/memory", path=path)

    assert memory["in_doubt"] is None


def test_rejecting_a_doubt_through_the_decide_route_clears_the_in_doubt_mark(
    console: Console, signed_out: ConsoleClient
) -> None:
    path, dana, ash = a_doubted_team(console, signed_out, "olive-doubts-rejected", 5407)
    challenge_id = doubt(dana, path, "misled")
    doubt(ash, path, "misled")

    rejected = signed_out.post_json(f"/api/challenges/{challenge_id}/decide", {"decision": "reject"})

    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["waiting"] == []
    memory = ask(signed_out, "/api/memory", path=path)
    assert memory["status"] == "active"
    assert memory["in_doubt"] is None


def test_accepting_a_doubt_through_the_decide_route_retires_the_memory(
    console: Console, signed_out: ConsoleClient
) -> None:
    path, dana, ash = a_doubted_team(console, signed_out, "olive-doubts-accepted", 5408)
    challenge_id = doubt(dana, path, "contradicts_code", **TAX_LINE)

    accepted = signed_out.post_json(f"/api/challenges/{challenge_id}/decide", {"decision": "accept"})

    assert accepted.status_code == 200, accepted.text
    memory = ask(signed_out, "/api/memory", path=path)
    assert memory["status"] == "retired"
    assert memory["in_doubt"] is None


def test_a_doubt_a_member_raised_says_its_reason_in_their_raised_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-doubts-raised", 5409)
    project = owner.call("create_project", name="Billing")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    personal = dana.call("remember", **TAX)["path"]
    path = dana.call("promote", path=personal, level="project")["path"]
    # The owner doubts Dana's memory from a session, and reads it in the list of what she raised.
    challenge_id = doubt(owner.in_project(project, "billing-api"), path, "misled")

    raised = ask(signed_out, "/api/challenges")["raised"]

    assert [(one["challenge_id"], one["kind"], one["reason"]) for one in raised] == [
        (challenge_id, "doubt", "misled")
    ]
