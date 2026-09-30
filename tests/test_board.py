"""A project's board, read and changed through the tools a coding agent calls (ADR-0014)."""

from __future__ import annotations

from typing import Any

from tests.support import (
    Console,
    ConsoleClient,
    Session,
    Team,
    add,
    create,
    member,
    signed_in_owner,
)


def card(session: Session, title: str, **fields: Any) -> dict[str, Any]:
    added: dict[str, Any] = session.call("add_card", title=title, **fields)
    return added


def numbers(cards: list[dict[str, Any]]) -> list[int]:
    return [one["number"] for one in cards]


def column(session: Session, name: str) -> list[int]:
    """The cards in one column, top first."""
    return numbers(session.call("board")["columns"][name])


def everywhere(board: dict[str, Any]) -> list[int]:
    """Every card on a board, column by column."""
    return [number for cards in board["columns"].values() for number in numbers(cards)]


def test_cards_are_numbered_within_their_project(team: Team, owner: Session) -> None:
    payments = team.owner().call("create_project", name="Payments")["project_id"]
    in_payments = team.owner().in_project(payments, "payments-api")

    added = [
        card(owner, "Retry failed webhooks")["number"],
        card(in_payments, "Refund partial charges")["number"],
        card(owner, "Split the invoice module")["number"],
        card(in_payments, "Show refunds on receipts")["number"],
        card(owner, "Drop the legacy exporter")["number"],
    ]

    assert added == [1, 1, 2, 2, 3]
    assert column(owner, "to_do") == [1, 2, 3]
    assert column(in_payments, "to_do") == [1, 2]


def test_a_new_card_goes_to_the_bottom_of_to_do_with_normal_priority(owner: Session) -> None:
    card(owner, "Retry failed webhooks")

    added = card(owner, "Split the invoice module", description="The module is 3,000 lines.")

    assert added["column"] == "to_do"
    assert added["priority"] == "normal"
    assert added["creator"] == "owner-1"
    assert added["assignee"] is None
    assert added["description"] == "The module is 3,000 lines."
    assert column(owner, "to_do") == [1, 2]
    assert [column(owner, name) for name in ("doing", "blocked", "done")] == [[], [], []]


def test_the_board_filters_by_column_assignee_label_priority_and_text(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks", labels=["billing", "reliability"], priority="high")
    card(owner, "Split the invoice module", description="Invoices and credit notes are tangled.", labels=["billing"])
    card(owner, "Upgrade the queue client", priority="low", labels=["chores"])
    owner.call("update_card", number=2, assignee="emp-2")
    owner.call("update_card", number=3, column="doing")

    assert everywhere(owner.call("board", column="doing")) == [3]
    assert everywhere(owner.call("board", assignee="emp-2")) == [2]
    assert everywhere(owner.call("board", label="billing")) == [1, 2]
    assert everywhere(owner.call("board", priority="high")) == [1]
    assert everywhere(owner.call("board", priority="normal")) == [2]
    assert everywhere(owner.call("board", text="CREDIT NOTES")) == [2]
    assert everywhere(owner.call("board", text="webhooks")) == [1]
    assert everywhere(owner.call("board", label="billing", priority="high")) == [1]
    assert everywhere(dana.call("board", assignee="emp-2")) == [2]


def test_the_board_suggests_the_labels_already_on_it(owner: Session) -> None:
    card(owner, "Retry failed webhooks", labels=["reliability", "billing"])
    card(owner, "Split the invoice module", labels=["billing"])

    assert owner.call("board")["labels"] == ["billing", "reliability"]
    assert owner.call("board", column="doing")["labels"] == ["billing", "reliability"]


def test_a_priority_or_column_the_board_does_not_have_is_refused(owner: Session) -> None:
    card(owner, "Retry failed webhooks")

    assert "High, Normal or Low" in owner.refusal("add_card", title="Tidy up", priority="urgent")
    assert "To do, Doing, Blocked or Done" in owner.refusal("update_card", number=1, column="review")
    assert "To do, Doing, Blocked or Done" in owner.refusal("board", column="later")


def test_a_card_moves_between_to_do_doing_blocked_and_done(owner: Session) -> None:
    card(owner, "Retry failed webhooks")

    moved = [owner.call("update_card", number=1, column=name)["column"] for name in ("doing", "blocked", "done", "to_do")]

    assert moved == ["doing", "blocked", "done", "to_do"]
    assert column(owner, "to_do") == [1]


def test_the_columns_are_named_as_the_board_shows_them_too(owner: Session) -> None:
    card(owner, "Retry failed webhooks", priority="High")

    moved = owner.call("update_card", number=1, column="To do")

    assert moved["column"] == "to_do"
    assert moved["priority"] == "high"


def test_a_card_is_reordered_within_its_column(owner: Session) -> None:
    for title in ("Retry failed webhooks", "Split the invoice module", "Upgrade the queue client"):
        card(owner, title)

    owner.call("update_card", number=3, position=1)
    after_the_first = column(owner, "to_do")
    owner.call("update_card", number=3, position=3)
    to_the_bottom = column(owner, "to_do")
    owner.call("update_card", number=1, position=99)

    assert after_the_first == [3, 1, 2]
    assert to_the_bottom == [1, 2, 3]
    assert column(owner, "to_do") == [2, 3, 1]


def test_a_card_moved_to_another_column_goes_where_it_is_put(owner: Session) -> None:
    for title in ("Retry failed webhooks", "Split the invoice module", "Upgrade the queue client"):
        card(owner, title)
    owner.call("update_card", number=1, column="doing")
    owner.call("update_card", number=2, column="doing")

    owner.call("update_card", number=3, column="doing", position=1)

    assert column(owner, "doing") == [3, 1, 2]
    assert column(owner, "to_do") == []


def test_update_card_changes_only_the_fields_it_is_given(owner: Session) -> None:
    path = owner.call(
        "remember", title="Webhooks retry", summary="Webhooks retry.", type="gotcha", body="Webhooks retry twice."
    )["path"]
    card(owner, "Retry failed webhooks", description="They fail silently.", labels=["billing"], priority="high")

    changed = owner.call(
        "update_card",
        number=1,
        title="Retry failed webhooks with backoff",
        due_date="2026-10-15",
        memories=[path],
        files=["billing-api:src/webhooks/retry.py"],
    )

    assert changed["title"] == "Retry failed webhooks with backoff"
    assert changed["description"] == "They fail silently."
    assert changed["labels"] == ["billing"]
    assert changed["priority"] == "high"
    assert changed["due_date"] == "2026-10-15"
    assert changed["memories"] == [path]
    assert changed["files"] == ["billing-api:src/webhooks/retry.py"]
    assert owner.call("board")["columns"]["to_do"] == [changed]


def test_a_due_date_or_labels_can_be_cleared(owner: Session) -> None:
    card(owner, "Retry failed webhooks", labels=["billing"], due_date="2026-10-15")

    cleared = owner.call("update_card", number=1, labels=[], due_date="")

    assert cleared["labels"] == []
    assert cleared["due_date"] is None


def test_links_and_dates_that_are_not_well_formed_are_refused(owner: Session) -> None:
    card(owner, "Retry failed webhooks")

    assert "repository:path" in owner.refusal("update_card", number=1, files=["src/webhooks/retry.py"])
    assert "not a memory path" in owner.refusal("update_card", number=1, memories=["notes/webhooks"])
    assert "YYYY-MM-DD" in owner.refusal("update_card", number=1, due_date="next Friday")
    assert "needs a title" in owner.refusal("add_card", title="   ")


def test_a_description_over_the_memory_word_limit_is_refused(owner: Session) -> None:
    limit = owner.server.settings.memory_word_limit
    too_long = " ".join(["word"] * (limit + 1))
    card(owner, "Retry failed webhooks")

    on_adding = owner.refusal("add_card", title="Split the invoice module", description=too_long)
    on_updating = owner.refusal("update_card", number=1, description=too_long)

    assert f"the limit is {limit} words" in on_adding
    assert f"the limit is {limit} words" in on_updating
    assert column(owner, "to_do") == [1]
    assert owner.call("board")["columns"]["to_do"][0]["description"] == ""


def test_a_card_the_board_does_not_have_is_refused(team: Team, owner: Session) -> None:
    payments = team.owner().call("create_project", name="Payments")["project_id"]
    card(team.owner().in_project(payments, "payments-api"), "Refund partial charges")

    assert "no card 1" in owner.refusal("update_card", number=1, title="Mine now")


def test_an_assignee_must_be_a_member_of_the_team(owner: Session) -> None:
    card(owner, "Retry failed webhooks")

    assert "No member with member ID 'emp-9'" in owner.refusal("update_card", number=1, assignee="emp-9")


def test_an_assignee_can_be_taken_off(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    owner.call("update_card", number=1, assignee="emp-2")

    taken_off = owner.call("update_card", number=1, assignee="")

    assert taken_off["assignee"] is None


def test_the_board_needs_a_project(team: Team) -> None:
    unconnected = team.owner()

    assert "isn't connected to a project" in unconnected.refusal("board")
    assert "isn't connected to a project" in unconnected.refusal("add_card", title="Retry failed webhooks")


def test_a_member_outside_a_restricted_project_cannot_read_or_change_its_board(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-board-closed", 1101)
    billing = create(signed_out, "Billing")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(billing)
    card(owner.in_project(billing), "Retry failed webhooks")
    restricting = signed_out.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text

    refusals = [
        dana.refusal("board"),
        dana.refusal("add_card", title="Split the invoice module"),
        dana.refusal("update_card", number=1, column="doing"),
    ]

    assert all("is restricted" in refusal for refusal in refusals)
    assert column(owner.in_project(billing), "to_do") == [1]
    assert "can't reach project" in owner.in_project(billing).refusal("update_card", number=1, assignee="emp-2")


def test_each_change_to_a_card_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-board-audit", 1102)
    billing = create(signed_out, "Billing")["project_id"]
    in_billing = owner.in_project(billing).as_agent("claude-code")

    card(in_billing, "Retry failed webhooks")
    in_billing.call("update_card", number=1, priority="high", labels=["billing"])
    in_billing.call("update_card", number=1, column="doing")
    in_billing.call("update_card", number=1, position=1)
    in_billing.call("board")

    response = signed_out.get(f"/api/audit?project={billing}")
    assert response.status_code == 200, response.text
    events = [event for event in response.json()["events"] if event["kind"].startswith("card_")]
    assert [event["kind"] for event in events] == ["card_moved", "card_moved", "card_edited", "card_added"]
    assert {event["target"] for event in events} == {"card 1"}
    assert {event["actor"] for event in events} == {"E1001"}
    assert events[2]["detail"]["changed"] == ["priority", "labels"]
    assert events[1]["detail"]["from"] == "to_do"
    assert events[1]["detail"]["to"] == "doing"
    assert events[3]["detail"]["title"] == "Retry failed webhooks"
    assert all(event["detail"]["agent"] == "Claude Code" for event in events)


def test_a_member_of_the_project_changes_a_card_another_member_added(team: Team, owner: Session) -> None:
    cole = member(team, owner.project or "", "emp-3", "Cole Coder")
    card(owner, "Retry failed webhooks")

    moved = cole.call("update_card", number=1, column="doing")

    assert moved["column"] == "doing"
    assert moved["creator"] == "owner-1"
