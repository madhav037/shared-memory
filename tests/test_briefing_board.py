"""The board in the briefing: a member's own cards and their project's known issues, within the briefing's cap."""

from __future__ import annotations

from tests.support import Console, ConsoleClient, Session, add, added_context, create, signed_in_owner
from tests.test_board import card
from tests.test_briefing import promote
from tests.test_known_issues import FLAKY_UPLOADS, saved

# The tests' clock starts on 2026-09-01.
STALE_CACHE = {
    "title": "Stale prices after a deploy",
    "summary": "Prices stay stale for ten minutes after a deploy.",
    "body": "The price cache is not flushed on deploy, so prices stay stale for ten minutes.\n\n"
    "Workaround: flush the price cache by hand after deploying.",
}


def briefed(session: Session) -> str:
    """The briefing the session-start hook injects, checked to be the one the briefing tool fetches."""
    briefing = added_context(session.start())
    assert session.call("briefing", session=session.identifier) == briefing
    return briefing


def in_order(text: str, *parts: str) -> bool:
    places = [text.index(part) for part in parts]
    return places == sorted(places)


def test_the_briefing_shows_your_due_cards_then_doing_and_blocked_then_known_issues(owner: Session) -> None:
    pinned = promote(owner, "Use pnpm, not npm", "We use pnpm for every package.")
    owner.call("pin", path=pinned)
    card(owner, "Rotate the signing keys", due_date="2026-08-30")
    owner.call("update_card", number=1, assignee="owner-1")
    card(owner, "Retry failed webhooks", due_date="2026-09-01")
    owner.call("claim_card", number=2)
    card(owner, "Split the invoice module")
    owner.call("claim_card", number=3)
    card(owner, "Upgrade the queue client")
    owner.call("claim_card", number=4)
    owner.call("update_card", number=4, column="blocked", blocked_reason="Waiting on the payment provider's sandbox.")
    card(owner, "Drop the legacy exporter", due_date="2026-09-20")
    owner.call("update_card", number=5, assignee="owner-1")
    card(owner, "Archive old invoices", due_date="2026-08-20")
    owner.call("claim_card", number=6)
    owner.call("update_card", number=6, column="done")
    saved(owner, FLAKY_UPLOADS)

    briefing = briefed(owner)

    assert in_order(
        briefing,
        "Use pnpm, not npm",
        'card 1 "Rotate the signing keys" (To do, overdue: due 2026-08-30)',
        'card 2 "Retry failed webhooks" (Doing, due today)',
        'card 3 "Split the invoice module" (Doing)',
        "card 4 \"Upgrade the queue client\" (Blocked: Waiting on the payment provider's sandbox.)",
        "- Large uploads time out behind the proxy",
    )
    assert briefing.count("Retry failed webhooks") == 1
    assert "Drop the legacy exporter" not in briefing
    assert "Archive old invoices" not in briefing
    assert "Fix: Large uploads" not in briefing
    assert "more of your cards" not in briefing


def test_other_members_cards_never_appear_in_your_briefing(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)
    card(owner, "Split the invoice module")
    owner.call("claim_card", number=2)

    # A teammate's card in Doing may still be named as their session's activity, which is not a card of yours.
    assert 'card 1 "Retry failed webhooks"' not in briefed(owner)
    assert 'card 1 "Retry failed webhooks" (Doing)' in briefed(dana)
    assert 'card 2 "Split the invoice module"' not in briefed(dana)


def test_past_the_cap_what_does_not_fit_is_counted(owner: Session) -> None:
    long_body = " ".join(["Billing charges are retried with exponential backoff."] * 80)
    owner.call("pin", path=promote(owner, "Retry policy", long_body))
    for number in range(1, 21):
        card(owner, f"Retry failed webhooks from the payment provider, batch {number}")
        owner.call("claim_card", number=number)
    saved(owner, FLAKY_UPLOADS)
    saved(owner, STALE_CACHE)

    briefing = briefed(owner)

    shown = sum(f'card {number} "' in briefing for number in range(1, 21))
    assert len(briefing) // 4 <= 1500
    assert 0 < shown < 20
    assert f"{20 - shown} more of your cards" in briefing
    assert "2 more known issues" in briefing
    assert "Large uploads time out behind the proxy" not in briefing


def test_a_restricted_projects_known_issues_reach_only_its_access_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-briefing-closed", 1201)
    billing = create(signed_out, "Billing")["project_id"]
    in_billing = owner.in_project(billing)
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(billing)
    saved(in_billing, FLAKY_UPLOADS)
    restricting = signed_out.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text

    assert "Large uploads time out behind the proxy" in briefed(in_billing)
    assert "Large uploads time out behind the proxy" not in added_context(dana.start())
