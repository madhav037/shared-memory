"""Deciding a doubt (#536, spec #502): accepting it retires the memory, rejecting it lets the memory stand, and every
member who added evidence is told how it ended. The author editing or superseding the memory in a session settles its
open doubts. Driven through the Session driver over HTTP."""

from __future__ import annotations

from typing import Any

from tests.support import Session, Company, added_context, member, promote_keeping_both

TAX = {
    "title": "Sales tax is fifteen percent",
    "summary": "Invoices add fifteen percent sales tax.",
    "type": "convention",
    "body": "Every invoice adds a flat fifteen percent sales tax on the subtotal.",
}
# The same memory put right, worded so closely that promoting it finds TAX similar.
TAX_FIXED = {
    "title": "Sales tax is twenty percent",
    "summary": "Invoices add twenty percent sales tax.",
    "type": "convention",
    "body": "Every invoice adds a flat twenty percent sales tax on the subtotal.",
}
WEBHOOKS = {
    "title": "Webhooks retry for a day",
    "summary": "A failed webhook is retried for twenty-four hours.",
    "type": "gotcha",
    "body": "The relay retries a failed webhook delivery with backoff for twenty-four hours before giving up.",
}
TAX_LINE = {"code_reference": "billing-api:src/tax.py:42", "quoted_line": "RATE = Decimal('0.20')"}


def doubt(session: Session, path: str, reason: str = "misled", **extra: Any) -> int:
    raised = session.call("challenge", path=path, reason=reason, **extra)
    return int(raised["challenge_id"])


def news(session: Session) -> str:
    """What the member's next briefing tells them."""
    return added_context(session.start())


def found(session: Session, path: str) -> dict[str, bool]:
    """Whether search and recall still bring the memory up, to a session it has not been recalled in yet."""
    searched = [one["path"] for one in session.call("search", query="what sales tax do invoices add")["results"]]
    prompt = "Does every invoice add a flat fifteen percent sales tax on the subtotal?"
    recalled = added_context(session.prompt(prompt)).partition("<shared-memory-recall>")[2].partition("</shared-memory-recall>")[0]
    return {"search": path in searched, "recall": path in recalled}


def test_accepting_a_doubt_retires_the_memory_so_recall_and_search_no_longer_find_it(
    owner: Session, dana: Session
) -> None:
    path = promote_keeping_both(owner, TAX)
    challenge_id = doubt(dana, path, "contradicts_code", **TAX_LINE)
    before = found(dana.as_session("before"), path)

    accepted = owner.call("decide_challenge", challenge_id=challenge_id, decision="accept")

    assert accepted == {"status": "accepted", "challenge_id": challenge_id, "retired": path}
    assert before == {"search": True, "recall": True}
    assert owner.call("read", path=path)["status"] == "retired"
    assert found(dana.as_session("after"), path) == {"search": False, "recall": False}


def test_rejecting_a_doubt_closes_it_and_the_memory_stands(owner: Session, dana: Session) -> None:
    path = promote_keeping_both(owner, TAX)
    challenge_id = doubt(dana, path)

    rejected = owner.call("decide_challenge", challenge_id=challenge_id, decision="reject")

    assert rejected == {"status": "rejected", "challenge_id": challenge_id}
    read = owner.call("read", path=path)
    assert read["status"] == "active"
    assert read["open_challenges"] == []
    assert found(dana, path)["search"] is True


def test_every_member_who_added_evidence_is_told_a_rejection_once(
    company: Company, owner: Session, dana: Session
) -> None:
    cole = member(company, dana.project or "", "emp-3", "Cole Coder")
    path = promote_keeping_both(owner, TAX)
    challenge_id = doubt(dana, path, reasoning="My invoices came out wrong.")
    doubt(cole, path)
    doubt(dana.as_session("another-session"), path)

    owner.call("decide_challenge", challenge_id=challenge_id, decision="reject")

    told = f"Your challenge {challenge_id} against {path} was rejected by owner-1. The memory stands as it is."
    assert [news(one).count(told) for one in (dana, cole)] == [1, 1]
    assert "Your memory stays where it is" not in news(dana)


def test_every_member_who_added_evidence_is_told_an_acceptance_once(
    company: Company, owner: Session, dana: Session
) -> None:
    cole = member(company, dana.project or "", "emp-3", "Cole Coder")
    path = promote_keeping_both(owner, TAX)
    challenge_id = doubt(dana, path)
    doubt(cole, path)
    doubt(cole.as_session("another-session"), path)

    owner.call("decide_challenge", challenge_id=challenge_id, decision="accept")

    told = f"Your challenge {challenge_id} was accepted by owner-1: {path} is retired."
    assert [news(one).count(told) for one in (dana, cole)] == [1, 1]


def test_accepting_one_doubt_closes_the_other_reasons_doubt_and_tells_each_of_its_raisers(
    company: Company, owner: Session, dana: Session
) -> None:
    cole = member(company, dana.project or "", "emp-3", "Cole Coder")
    path = promote_keeping_both(owner, TAX)
    accepted = doubt(dana, path, "contradicts_code", **TAX_LINE)
    other = doubt(dana, path)
    doubt(cole, path)

    owner.call("decide_challenge", challenge_id=accepted, decision="accept")

    closed = f"Your challenge {other} against {path} was closed: challenge {accepted} by emp-2 was accepted instead."
    assert news(cole).count(closed) == 1
    assert news(dana).count(closed) == 1
    assert owner.call("read", path=path)["open_challenges"] == []


def test_the_author_editing_the_memory_in_a_session_closes_its_open_doubts_as_resolved_and_tells_each_raiser(
    company: Company, dana: Session
) -> None:
    cole = member(company, dana.project or "", "emp-3", "Cole Coder")
    path = dana.call("remember", **WEBHOOKS)["path"]
    misled = doubt(cole, path, reasoning="My webhook gave up after an hour.")
    contradicts = doubt(dana.as_session("another-session"), path, "contradicts_code", **TAX_LINE)
    doubt(dana.as_session("a-third-session"), path)
    news(dana)
    news(cole)

    dana.call("edit_memory", path=path, body="The relay retries a failed webhook delivery for twelve hours.")

    read = dana.call("read", path=path)
    assert read["status"] == "active"
    assert read["open_challenges"] == []

    def closed(challenge_id: int) -> str:
        return f"Your challenge {challenge_id} against {path} was closed: resolved, its author edited it."

    told_cole, told_dana = news(cole), news(dana)
    assert (told_cole.count(closed(misled)), told_cole.count(closed(contradicts))) == (1, 0)
    assert (told_dana.count(closed(misled)), told_dana.count(closed(contradicts))) == (1, 1)


def test_the_author_superseding_the_memory_in_a_session_closes_its_open_doubts_as_resolved_and_tells_each_raiser(
    company: Company, owner: Session, dana: Session
) -> None:
    cole = member(company, dana.project or "", "emp-3", "Cole Coder")
    path = promote_keeping_both(owner, TAX)
    challenge_id = doubt(dana, path, "contradicts_code", **TAX_LINE)
    doubt(cole, path, "contradicts_code", **TAX_LINE)
    personal = owner.call("remember", **TAX_FIXED)["path"]
    similar = owner.call("promote", path=personal, level="project")
    assert similar["status"] == "similar_memories", similar

    superseded = owner.call(
        "promote",
        path=personal,
        level="project",
        reference=similar["reference"],
        resolutions={one["path"]: ("supersede" if one["path"] == path else "keep_both") for one in similar["similar"]},
    )

    assert superseded["status"] == "promoted", superseded
    assert owner.call("read", path=path)["status"] == "superseded"
    told = (
        f"Your challenge {challenge_id} against {path} was closed: resolved, its author superseded it with "
        f"{superseded['path']}."
    )
    assert [news(one).count(told) for one in (dana, cole)] == [1, 1]
