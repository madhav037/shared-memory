"""What a challenge carries is bounded, and stays within what each member reaches: reasoning and code references have
limits, a member's second retire of one memory is their first, a briefing shows a few pieces of evidence and code
references and counts the rest, and what a doubt raised from a project a member can't reach brought is not shown to
them."""

from __future__ import annotations

from typing import Any

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
    promote_now,
    signed_in,
    signed_in_owner,
)

RULE = {"title": "Invoice numbers", "summary": "Invoices number by year.", "type": "convention",
        "body": "Invoices are numbered by year."}  # fmt: skip
TOO_LONG = "word " * 400  # 2,000 characters


def doubt(session: Session, path: str, reason: str = "misled", **extra: Any) -> dict[str, Any]:
    raised: dict[str, Any] = session.call("challenge", path=path, reason=reason, **extra)
    return raised


def test_reasoning_past_its_limit_is_refused(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RULE)

    on_retire = dana.refusal("retire", path=path, reasoning=TOO_LONG)
    on_doubt = dana.refusal("challenge", path=path, reason="misled", reasoning=TOO_LONG)

    assert "1500 characters" in on_retire and "1500 characters" in on_doubt
    assert dana.call("read", path=path)["open_challenges"] == []


def test_a_code_reference_past_its_limit_is_refused(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RULE)

    long_path = dana.refusal(
        "challenge", path=path, reason="contradicts_code", code_reference=f"billing-api:{'a/' * 200}x.py:1",
        quoted_line="RATE = 1",
    )  # fmt: skip
    long_line = dana.refusal(
        "challenge", path=path, reason="contradicts_code", code_reference=f"billing-api:src/x.py:{'9' * 5000}",
        quoted_line="RATE = 1",
    )  # fmt: skip

    assert "repository:path:line" in long_path and "repository:path:line" in long_line


def test_a_members_second_retire_of_a_memory_is_their_first(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RULE)

    first = dana.call("retire", path=path, reasoning="No longer true.")
    second = dana.call("retire", path=path, reasoning="Still no longer true.")

    assert second["challenge_id"] == first["challenge_id"]
    assert [one["kind"] for one in owner.call("read", path=path)["open_challenges"]] == ["retire"]


def test_a_briefing_shows_a_few_pieces_of_evidence_and_code_references_and_counts_the_rest(
    owner: Session, dana: Session
) -> None:
    path = promote_now(owner, RULE)
    for number in range(1, 9):
        doubt(
            dana.as_session(f"session-{number}"), path, "contradicts_code",
            code_reference=f"billing-api:src/invoice{number}.py:{number}", quoted_line=f"NUMBER = {number}",
        )  # fmt: skip

    briefing = added_context(owner.start())
    in_doubt = owner.call("read", path=path)["in_doubt"]

    assert briefing.count("  - emp-2 quotes") == 5
    assert "  - and 3 more" in briefing
    assert "invoice3.py:3" in in_doubt and "invoice4.py" not in in_doubt and "and 5 more" in in_doubt


def restrict(client: ConsoleClient, project: str) -> None:
    closed = client.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    assert closed.status_code == 200, closed.text


def test_a_challenge_from_a_project_the_reader_cant_reach_is_shown_by_its_number_alone(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-bounded-one", 7101)
    billing, payments = create(signed_out, "Billing")["project_id"], create(signed_out, "Payments")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev", "dana-bounded-one")["personal_token"])
    target = promote_keeping_both(dana.in_project(payments, "payments-api"), RULE, "company")
    restrict(signed_out, billing)
    raised = challenge(owner.in_project(billing, "billing-api"), {**RULE, "title": "Invoices number by month"}, target,
                       "company", reasoning="HIDDEN-REASONING")  # fmt: skip

    (seen,) = dana.in_project(payments, "payments-api").call("read", path=target)["open_challenges"]

    assert seen["challenge_id"] == raised["challenge_id"]
    assert seen["challenger_path"] is None
    (owners,) = owner.in_project(billing, "billing-api").call("read", path=target)["open_challenges"]
    assert owners["challenger_path"] is not None and billing in owners["challenger_path"], "who reaches it sees it"


def test_a_doubt_raised_from_a_project_the_reader_cant_reach_shows_none_of_what_it_brought(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-bounded-two", 7103)
    billing, payments = create(signed_out, "Billing")["project_id"], create(signed_out, "Payments")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev", "dana-bounded-two")["personal_token"])
    target = promote_keeping_both(dana.in_project(payments, "payments-api"), RULE, "company")
    restrict(signed_out, billing)

    doubt(
        owner.in_project(billing, "billing-api"), target, "contradicts_code", reasoning="HIDDEN-REASONING",
        code_reference="billing-api:src/secret.py:7", quoted_line="HIDDEN_LINE = 1",
    )  # fmt: skip
    told = added_context(dana.in_project(payments, "payments-api").prompt("hello"))
    detail = ask(signed_in(console, "dana-bounded-two", 7104), "/api/memory", path=target)

    assert "a doubt" in told, "the author still learns their memory is doubted"
    assert "HIDDEN-REASONING" not in told and "HIDDEN_LINE" not in told
    (evidence,) = detail["open_challenges"][0]["evidence"]
    assert (evidence["reasoning"], evidence["quoted_line"], evidence["code_reference"]) == (None, None, None)
    assert "secret.py" not in str(detail), "nor does the in-doubt mark name its code"
    assert "secret.py" not in str(dana.in_project(payments, "payments-api").call("read", path=target))
    (owners,) = ask(signed_out, "/api/memory", path=target)["open_challenges"][0]["evidence"]
    assert owners["reasoning"] == "HIDDEN-REASONING", "who reaches the project still sees it"
    assert "secret.py" in owner.in_project(billing, "billing-api").call("read", path=target)["in_doubt"]
