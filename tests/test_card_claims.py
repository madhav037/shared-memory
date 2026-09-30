"""Who may change a card on a project's board, claiming one, commenting on one, and what happens to a member's cards
when they lose the project (ADR-0006, ADR-0014)."""

from __future__ import annotations

from typing import Any

from tests.support import (
    Console,
    ConsoleClient,
    Session,
    Team,
    ToolRefused,
    add,
    create,
    member,
    signed_in_owner,
)
from tests.test_board import card, column


def the_card(session: Session, number: int) -> dict[str, Any]:
    """One card as the board shows it."""
    board = session.call("board")
    return next(one for cards in board["columns"].values() for one in cards if one["number"] == number)


def led_by_dana(team: Team, dana: Session) -> tuple[Session, Session, Session]:
    """A project Dana created, so she leads it, with Cole working in it and the team's owner, who doesn't lead it."""
    payments = dana.call("create_project", name="Payments")["project_id"]
    cole = member(team, payments, "emp-3", "Cole Coder")
    return dana.in_project(payments, "payments-api"), cole, team.owner().in_project(payments, "payments-api")


# Claiming


def test_claiming_a_card_makes_you_its_assignee_and_moves_it_to_doing(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    card(owner, "Split the invoice module")
    owner.call("claim_card", number=2)

    claimed = dana.call("claim_card", number=1)

    assert claimed["assignee"] == "emp-2"
    assert claimed["column"] == "doing"
    assert column(owner, "doing") == [2, 1]
    assert column(owner, "to_do") == []


def test_a_card_someone_has_claimed_is_refused_naming_its_assignee(owner: Session, dana: Session, cole: Session) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)

    refused = cole.refusal("claim_card", number=1)

    assert "Dana Dev (emp-2)" in refused
    assert the_card(owner, 1)["assignee"] == "emp-2"
    assert "already yours" in dana.refusal("claim_card", number=1)


def test_two_claims_racing_on_one_card_exactly_one_wins(owner: Session, dana: Session, cole: Session) -> None:
    for attempt in range(5):
        number = card(owner, f"Retry failed webhooks, attempt {attempt}")["number"]
        racing = {"emp-2": dana.call_soon("claim_card", number=number), "emp-3": cole.call_soon("claim_card", number=number)}

        won, refused = [], []
        for member_id, future in racing.items():
            try:
                won.append(future.result(timeout=30)["assignee"])
            except ToolRefused as refusal:
                refused.append((member_id, str(refusal)))

        assert len(won) == 1
        assert len(refused) == 1
        assert refused[0][0] != won[0]
        assert f"({won[0]})" in refused[0][1]
        assert the_card(owner, number)["assignee"] == won[0]
        assert column(owner, "doing")[-1] == number


def test_only_a_card_in_to_do_can_be_claimed(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    owner.call("update_card", number=1, column="blocked")

    assert "only cards in To do" in dana.refusal("claim_card", number=1)
    assert the_card(owner, 1)["assignee"] is None
    assert "no card 7" in dana.refusal("claim_card", number=7)


# Who may change a card


def test_any_member_edits_and_moves_an_unassigned_card(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")

    dana.call("update_card", number=1, title="Retry failed webhooks with backoff", labels=["billing"])
    moved = dana.call("update_card", number=1, column="blocked")

    assert moved["title"] == "Retry failed webhooks with backoff"
    assert moved["labels"] == ["billing"]
    assert moved["column"] == "blocked"


def test_a_member_cannot_change_a_card_someone_else_is_assigned(owner: Session, dana: Session, cole: Session) -> None:
    card(owner, "Retry failed webhooks")
    card(owner, "Split the invoice module")
    dana.call("claim_card", number=1)

    refusals = [
        cole.refusal("update_card", number=1, title="Mine now"),
        cole.refusal("update_card", number=1, column="done"),
        cole.refusal("update_card", number=1, position=2),
        cole.refusal("update_card", number=1, assignee="emp-3"),
        cole.refusal("delete_card", number=1),
    ]

    assert all("Dana Dev (emp-2)" in refusal for refusal in refusals)
    assert all("comment_card" in refusal for refusal in refusals)
    kept = the_card(owner, 1)
    assert (kept["title"], kept["column"], kept["assignee"]) == ("Retry failed webhooks", "doing", "emp-2")


def test_the_assignee_edits_moves_hands_over_and_deletes_their_card(owner: Session, dana: Session, cole: Session) -> None:
    card(cole, "Retry failed webhooks")
    card(cole, "Split the invoice module")
    dana.call("claim_card", number=1)
    dana.call("claim_card", number=2)

    edited = dana.call("update_card", number=1, title="Retry failed webhooks with backoff", column="blocked")
    handed_over = dana.call("update_card", number=1, assignee="emp-3")
    dana.call("delete_card", number=2)

    assert (edited["title"], edited["column"]) == ("Retry failed webhooks with backoff", "blocked")
    assert handed_over["assignee"] == "emp-3"
    assert "Cole Coder (emp-3)" in dana.refusal("update_card", number=1, column="done")
    assert column(owner, "doing") == []


def test_a_project_lead_does_anything_to_any_card_on_the_board(team: Team, dana: Session) -> None:
    lead, cole, _ = led_by_dana(team, dana)
    card(cole, "Retry failed webhooks")
    card(cole, "Split the invoice module")
    cole.call("claim_card", number=1)
    cole.call("claim_card", number=2)

    lead.call("update_card", number=1, title="Retry failed webhooks with backoff", priority="high")
    lead.call("update_card", number=1, column="to_do", position=1)
    reassigned = lead.call("update_card", number=1, assignee="emp-2")
    lead.call("delete_card", number=2)

    assert (reassigned["title"], reassigned["priority"], reassigned["assignee"]) == (
        "Retry failed webhooks with backoff", "high", "emp-2",
    )  # fmt: skip
    assert column(lead, "to_do") == [1]
    assert column(lead, "doing") == []


def test_an_admin_who_does_not_lead_the_project_does_anything_to_any_card(team: Team, dana: Session) -> None:
    _, cole, admin = led_by_dana(team, dana)
    card(cole, "Retry failed webhooks")
    card(cole, "Split the invoice module")
    cole.call("claim_card", number=1)
    cole.call("claim_card", number=2)

    admin.call("update_card", number=1, column="done")
    taken_off = admin.call("update_card", number=2, assignee="")
    admin.call("delete_card", number=1)

    assert taken_off["assignee"] is None
    assert column(admin, "done") == []
    assert column(admin, "doing") == [2]


def test_a_member_claims_rather_than_assigns(owner: Session, dana: Session, cole: Session) -> None:
    card(owner, "Retry failed webhooks")

    to_themselves = dana.refusal("update_card", number=1, assignee="emp-2")
    to_someone_else = dana.refusal("update_card", number=1, assignee="emp-3")

    assert "claim_card" in to_themselves
    assert "claim_card" in to_someone_else
    assert the_card(owner, 1)["assignee"] is None


def test_a_cards_creator_deletes_it_while_it_is_unassigned(owner: Session, dana: Session, cole: Session) -> None:
    card(dana, "Retry failed webhooks")
    card(dana, "Split the invoice module")
    card(dana, "Upgrade the queue client")
    cole.call("claim_card", number=3)

    not_the_creator = cole.refusal("delete_card", number=1)
    deleted = dana.call("delete_card", number=1)
    now_claimed = dana.refusal("delete_card", number=3)

    assert "creator" in not_the_creator
    assert deleted == {"deleted": 1}
    assert "Cole Coder (emp-3)" in now_claimed
    assert column(owner, "to_do") == [2]
    assert column(owner, "doing") == [3]


def test_a_deleted_cards_number_is_not_used_again(owner: Session) -> None:
    card(owner, "Retry failed webhooks")
    owner.call("delete_card", number=1)

    added = card(owner, "Split the invoice module")

    assert added["number"] == 2
    assert "no card 1" in owner.refusal("update_card", number=1, title="Back again")
    assert "no card 1" in owner.refusal("delete_card", number=1)


# Comments


def test_any_member_of_the_project_comments_on_any_card(owner: Session, dana: Session, cole: Session) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)

    cole.call("comment_card", number=1, text="The retry job also runs for refunds.")
    commented = dana.call("comment_card", number=1, text="  Good catch, I'll cover refunds too.  ")

    assert [(one["author"], one["text"]) for one in commented["comments"]] == [
        ("emp-3", "The retry job also runs for refunds."),
        ("emp-2", "Good catch, I'll cover refunds too."),
    ]
    assert the_card(owner, 1)["comments"] == commented["comments"]
    assert card(owner, "Split the invoice module")["comments"] == []


def test_a_comment_has_a_smaller_cap_than_a_description(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    description_limit = owner.server.settings.memory_word_limit
    owner.call("update_card", number=1, description=" ".join(["word"] * description_limit))

    too_long = dana.refusal("comment_card", number=1, text=" ".join(["word"] * description_limit))
    empty = dana.refusal("comment_card", number=1, text="   ")

    assert "the limit is" in too_long
    assert "empty" in empty
    assert the_card(owner, 1)["comments"] == []


# Losing the project


def test_a_removed_members_doing_and_blocked_cards_go_back_to_to_do_unassigned(
    owner: Session, dana: Session, cole: Session
) -> None:
    for title in ("Retry failed webhooks", "Split the invoice module", "Upgrade the queue client", "Drop the exporter"):
        card(owner, title)
    for number in (1, 2, 3, 4):
        (cole if number == 4 else dana).call("claim_card", number=number)
    dana.call("update_card", number=2, column="blocked")
    dana.call("update_card", number=3, column="done")

    owner.call("remove_member", member_id="emp-2")

    board = owner.call("board")["columns"]
    assert [(one["number"], one["assignee"]) for one in board["to_do"]] == [(1, None), (2, None)]
    assert [(one["number"], one["assignee"]) for one in board["doing"]] == [(4, "emp-3")]
    assert board["blocked"] == []
    assert [(one["number"], one["assignee"]) for one in board["done"]] == [(3, "emp-2")]


def test_taking_a_member_off_a_restricted_projects_access_list_returns_their_cards(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-board-access", 1201)
    billing = create(signed_out, "Billing")["project_id"]
    ledger = create(signed_out, "Ledger")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"])
    for project in (billing, ledger):
        card(owner.in_project(project), "Retry failed webhooks")
        dana.in_project(project).call("claim_card", number=1)
    for change in (f"/api/projects/{billing}/access", f"/api/projects/{billing}/restrict"):
        body = {"restricted": True} if change.endswith("restrict") else {"member_id": "emp-2"}
        response = signed_out.post_json(change, body)
        assert response.status_code == 200, response.text
    assert the_card(owner.in_project(billing), 1)["assignee"] == "emp-2"

    revoked = signed_out.post(f"/api/projects/{billing}/access/emp-2/remove")
    assert revoked.status_code == 200, revoked.text

    returned = the_card(owner.in_project(billing), 1)
    assert (returned["column"], returned["assignee"]) == ("to_do", None)
    kept = the_card(owner.in_project(ledger), 1)
    assert (kept["column"], kept["assignee"]) == ("doing", "emp-2")


def test_restricting_a_project_returns_the_cards_of_members_not_on_its_access_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-board-restrict", 1202)
    billing = create(signed_out, "Billing")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(billing)
    card(owner.in_project(billing), "Retry failed webhooks")
    card(owner.in_project(billing), "Split the invoice module")
    dana.call("claim_card", number=1)
    owner.in_project(billing).call("claim_card", number=2)

    restricting = signed_out.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text

    board = owner.in_project(billing).call("board")["columns"]
    assert [(one["number"], one["assignee"]) for one in board["to_do"]] == [(1, None)]
    assert [(one["number"], one["assignee"]) for one in board["doing"]] == [(2, "E1001")]


def test_a_member_outside_a_restricted_project_cannot_claim_comment_on_or_delete_its_cards(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-board-closed-claims", 1203)
    billing = create(signed_out, "Billing")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(billing)
    card(owner.in_project(billing), "Retry failed webhooks")
    restricting = signed_out.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text

    refusals = [
        dana.refusal("claim_card", number=1),
        dana.refusal("comment_card", number=1, text="Is this still needed?"),
        dana.refusal("delete_card", number=1),
    ]

    assert all("is restricted" in refusal for refusal in refusals)


def test_claims_comments_deletes_and_returned_cards_are_in_the_audit_log(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-board-claims-audit", 1204)
    billing = create(signed_out, "Billing")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(billing)
    in_billing = owner.in_project(billing).as_agent("claude-code")
    card(in_billing, "Retry failed webhooks")
    card(in_billing, "Split the invoice module")

    dana.as_agent("claude-code").call("claim_card", number=1)
    in_billing.call("comment_card", number=1, text="Refunds retry too.")
    in_billing.call("delete_card", number=2)
    removed = signed_out.post("/api/members/emp-2/remove")
    assert removed.status_code == 200, removed.text

    response = signed_out.get(f"/api/audit?project={billing}")
    assert response.status_code == 200, response.text
    events = [event for event in response.json()["events"] if event["kind"] not in ("card_added",)]
    kinds = [(event["kind"], event["actor"], event["target"]) for event in events if event["kind"].startswith("card_")]
    assert kinds == [
        ("card_returned", "E1001", "card 1"),
        ("card_deleted", "E1001", "card 2"),
        ("card_commented", "E1001", "card 1"),
        ("card_claimed", "emp-2", "card 1"),
    ]
    detail = {event["kind"]: event["detail"] for event in events}
    assert detail["card_returned"] == {"from": "doing", "assignee": "emp-2"}
    assert detail["card_deleted"] == {"title": "Split the invoice module", "agent": "Claude Code"}
    assert detail["card_claimed"] == {"agent": "Claude Code"}
