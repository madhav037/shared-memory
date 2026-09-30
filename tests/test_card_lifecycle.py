"""A card's life after it is claimed: Blocked with its reason, Done and the archive, reopening, and the notices a
member is sent about their cards (ADR-0014)."""

from __future__ import annotations

from tests.support import Session, Team, added_context
from tests.test_board import card, column, numbers
from tests.test_card_claims import led_by_dana, the_card


def briefing(session: Session) -> str:
    """What the member's next session starts with."""
    return added_context(session.start())


# Blocked


def test_moving_a_card_to_blocked_needs_a_reason(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)

    without = dana.refusal("update_card", number=1, column="blocked")
    blank = dana.refusal("update_card", number=1, column="blocked", blocked_reason="   ")
    blocked = dana.call("update_card", number=1, column="blocked", blocked_reason="Waiting on the payment provider's sandbox.")

    assert "reason" in without
    assert "reason" in blank
    assert (blocked["column"], blocked["blocked_reason"], blocked["waits_on"]) == (
        "blocked", "Waiting on the payment provider's sandbox.", None,
    )  # fmt: skip


def test_a_blocked_card_may_name_the_card_it_waits_on(owner: Session, dana: Session) -> None:
    card(owner, "Upgrade the queue client")
    card(owner, "Retry failed webhooks")
    card(owner, "Drop the legacy exporter")
    owner.call("update_card", number=3, column="done")

    blocked = dana.call("update_card", number=2, column="blocked", blocked_reason="Needs the new client.", waits_on=1)
    itself = dana.refusal("update_card", number=1, column="blocked", blocked_reason="Loops.", waits_on=1)
    missing = dana.refusal("update_card", number=1, column="blocked", blocked_reason="Nothing.", waits_on=9)
    finished = dana.refusal("update_card", number=1, column="blocked", blocked_reason="Done already.", waits_on=3)

    assert (blocked["blocked_reason"], blocked["waits_on"]) == ("Needs the new client.", 1)
    assert the_card(owner, 2)["waits_on"] == 1
    assert "itself" in itself
    assert "no card 9" in missing
    assert "Done" in finished
    assert column(owner, "blocked") == [2]


def test_a_reason_or_waits_on_is_only_for_a_card_in_blocked(owner: Session) -> None:
    card(owner, "Upgrade the queue client")
    card(owner, "Retry failed webhooks")

    refused = owner.refusal("update_card", number=2, blocked_reason="Waiting.")
    also_refused = owner.refusal("update_card", number=2, column="doing", waits_on=1)

    assert "Blocked" in refused
    assert "Blocked" in also_refused
    assert the_card(owner, 2)["column"] == "to_do"


def test_a_blocked_cards_reason_and_waits_on_change_while_it_stays_blocked(owner: Session) -> None:
    card(owner, "Upgrade the queue client")
    card(owner, "Retry failed webhooks")
    owner.call("update_card", number=2, column="blocked", blocked_reason="Waiting on the sandbox.")

    changed = owner.call("update_card", number=2, blocked_reason="Needs the new client.", waits_on=1)
    cleared = owner.call("update_card", number=2, waits_on=0)

    assert (changed["blocked_reason"], changed["waits_on"]) == ("Needs the new client.", 1)
    assert (cleared["blocked_reason"], cleared["waits_on"]) == ("Needs the new client.", None)


def test_leaving_blocked_clears_the_reason_and_the_card_waited_on(owner: Session) -> None:
    card(owner, "Upgrade the queue client")
    card(owner, "Retry failed webhooks")
    owner.call("update_card", number=2, column="blocked", blocked_reason="Needs the new client.", waits_on=1)

    moved = owner.call("update_card", number=2, column="doing")

    assert (moved["column"], moved["blocked_reason"], moved["waits_on"]) == ("doing", None, None)


def test_finishing_the_card_waited_on_tells_the_blocked_cards_assignee(
    owner: Session, dana: Session, cole: Session
) -> None:
    card(owner, "Upgrade the queue client")
    card(owner, "Retry failed webhooks")
    cole.call("claim_card", number=1)
    dana.call("claim_card", number=2)
    dana.call("update_card", number=2, column="blocked", blocked_reason="Needs the new client.", waits_on=1)
    briefing(dana)

    cole.call("update_card", number=1, column="done")

    told = briefing(dana)
    assert 'Card 1 "Upgrade the queue client"' in told
    assert 'card 2 "Retry failed webhooks"' in told
    assert "can go on" in told
    assert the_card(owner, 2)["column"] == "blocked"
    assert "can go on" not in briefing(dana)
    assert "can go on" not in briefing(cole)


def test_a_card_waiting_on_one_that_is_done_after_it_is_deleted_tells_no_one(owner: Session, dana: Session) -> None:
    card(owner, "Upgrade the queue client")
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=2)
    dana.call("update_card", number=2, column="blocked", blocked_reason="Needs the new client.", waits_on=1)

    owner.call("delete_card", number=1)

    assert the_card(owner, 2)["waits_on"] is None


# Done and the archive


def test_a_card_done_15_days_ago_is_off_the_board_and_in_the_archive(owner: Session) -> None:
    for title in ("Retry failed webhooks", "Split the invoice module", "Upgrade the queue client"):
        card(owner, title)
    owner.call("update_card", number=1, column="done")
    owner.server.clock.advance(days=13)
    owner.call("update_card", number=2, column="done")
    owner.server.clock.advance(days=2)

    board = owner.call("board")
    archive = owner.call("board", archive=True)

    assert numbers(board["columns"]["done"]) == [2]
    assert numbers(board["columns"]["to_do"]) == [3]
    assert numbers(archive["archive"]) == [1]
    assert archive["archive"][0]["title"] == "Retry failed webhooks"
    assert archive["archive"][0]["column"] == "done"


def test_a_card_done_14_days_ago_is_still_on_the_board(owner: Session) -> None:
    card(owner, "Retry failed webhooks")
    owner.call("update_card", number=1, column="done")
    owner.server.clock.advance(days=14, seconds=-1)

    assert column(owner, "done") == [1]
    assert owner.call("board", archive=True)["archive"] == []


def test_the_archive_is_newest_first_and_takes_the_boards_filters(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks", labels=["billing"])
    card(owner, "Split the invoice module", labels=["billing"])
    card(owner, "Upgrade the queue client")
    dana.call("claim_card", number=1)
    dana.call("claim_card", number=2)
    for number in (1, 2, 3):
        owner.call("update_card", number=number, column="done")
        owner.server.clock.advance(days=1)
    owner.server.clock.advance(days=20)

    assert numbers(owner.call("board", archive=True)["archive"]) == [3, 2, 1]
    assert numbers(owner.call("board", archive=True, label="billing")["archive"]) == [2, 1]
    assert numbers(owner.call("board", archive=True, assignee="emp-2", text="invoice")["archive"]) == [2]
    assert column(owner, "done") == []


# Reopening


def test_the_assignee_reopens_their_done_card(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)
    dana.call("update_card", number=1, column="done")

    reopened = dana.call("update_card", number=1, column="doing")

    assert (reopened["column"], reopened["assignee"]) == ("doing", "emp-2")


def test_a_lead_reopens_an_archived_card(team: Team, dana: Session) -> None:
    lead, cole, _ = led_by_dana(team, dana)
    card(cole, "Retry failed webhooks")
    cole.call("claim_card", number=1)
    cole.call("update_card", number=1, column="done")
    lead.server.clock.advance(days=30)

    reopened = lead.call("update_card", number=1, column="to_do")

    assert reopened["column"] == "to_do"
    assert column(lead, "to_do") == [1]
    assert lead.call("board", archive=True)["archive"] == []


def test_reopening_a_done_card_is_refused_for_anyone_else(owner: Session, dana: Session, cole: Session) -> None:
    card(owner, "Retry failed webhooks")
    card(owner, "Split the invoice module")
    dana.call("claim_card", number=1)
    dana.call("update_card", number=1, column="done")
    owner.call("update_card", number=2, column="done")

    assigned = cole.refusal("update_card", number=1, column="to_do")
    unassigned = cole.refusal("update_card", number=2, column="to_do")

    assert "Dana Dev (emp-2)" in assigned
    assert "reopen" in unassigned
    assert column(owner, "done") == [1, 2]


# Notices


def test_a_comment_on_your_card_is_in_your_next_briefing(owner: Session, dana: Session, cole: Session) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)
    briefing(dana)

    cole.call("comment_card", number=1, text="The retry job also runs for refunds.")
    dana.call("comment_card", number=1, text="Covering refunds too.")

    told = briefing(dana)
    assert 'Cole Coder (emp-3) commented on your card 1 "Retry failed webhooks"' in told
    assert "The retry job also runs for refunds." in told
    assert "Covering refunds too." not in told
    assert "commented" not in briefing(dana)


def test_being_given_a_card_or_having_it_taken_off_you_is_in_your_next_briefing(
    owner: Session, dana: Session, cole: Session
) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)
    briefing(dana)
    briefing(cole)

    owner.call("update_card", number=1, assignee="emp-3")

    to_cole = briefing(cole)
    to_dana = briefing(dana)
    assert 'Olive Owner (owner-1) assigned card 1 "Retry failed webhooks"' in to_cole
    assert "to you" in to_cole
    assert 'card 1 "Retry failed webhooks"' in to_dana
    assert "Cole Coder (emp-3)" in to_dana


def test_your_card_moved_out_of_blocked_by_someone_else_is_in_your_next_briefing(
    owner: Session, dana: Session
) -> None:
    card(owner, "Retry failed webhooks")
    card(owner, "Split the invoice module")
    dana.call("claim_card", number=1)
    dana.call("claim_card", number=2)
    dana.call("update_card", number=1, column="blocked", blocked_reason="Waiting on the sandbox.")
    dana.call("update_card", number=2, column="blocked", blocked_reason="Waiting on the sandbox.")
    briefing(dana)

    owner.call("update_card", number=1, column="doing")
    dana.call("update_card", number=2, column="doing")

    told = briefing(dana)
    assert 'Olive Owner (owner-1) unblocked your card 1 "Retry failed webhooks"' in told
    assert "unblocked your card 2" not in told


def test_a_project_lead_is_told_when_a_members_cards_go_back_to_to_do(team: Team, dana: Session) -> None:
    lead, cole, admin = led_by_dana(team, dana)
    card(cole, "Retry failed webhooks")
    card(cole, "Split the invoice module")
    cole.call("claim_card", number=1)
    cole.call("claim_card", number=2)
    briefing(lead)

    admin.call("remove_member", member_id="emp-3")

    told = briefing(lead)
    assert "Cole Coder (emp-3)" in told
    assert "cards 1, 2" in told
    assert "To do" in told
    assert "Cole Coder" not in briefing(lead)


def test_a_notice_is_in_the_briefing_of_a_session_in_another_project(team: Team, owner: Session, dana: Session) -> None:
    payments = team.owner().call("create_project", name="Payments")["project_id"]
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)

    owner.call("comment_card", number=1, text="Refunds retry too.")

    told = briefing(dana.in_project(payments))
    assert "Refunds retry too." in told
    assert f"in {owner.project}" in told
