"""What a member has been told, in the console: the notices about their cards, which also reach their next briefing.
Reading them here is only reading: a notice still waits for the member's coding agent, and no memory is written."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import Console, ConsoleClient, Session, add, added_context, ask, signed_in
from tests.test_console_board import a_board
from tests.test_console_never_writes_memory import watch_for_writes
from tests.test_known_issues import FLAKY_UPLOADS, saved


def notices(client: ConsoleClient) -> list[dict[str, Any]]:
    told: list[dict[str, Any]] = ask(client, "/api/notices")["notices"]
    return told


def a_teammate(console: Console, client: ConsoleClient, project: str, github: str) -> Session:
    added = add(client, "emp-2", "Dana Dev", github)
    return Session(console.server, added["personal_token"], project, "billing-api")


def test_a_comment_on_a_members_card_is_a_notice_naming_the_card(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-notices-one", 1501)
    dana = a_teammate(console, signed_out, project, "dana-notices-one")
    agent.call("add_card", title="Retry failed webhooks")
    agent.call("claim_card", number=1)

    assert notices(signed_out) == []
    dana.call("comment_card", number=1, text="Stripe retries for three days.")
    (told,) = notices(signed_out)

    assert told["text"] == (
        f'Dana Dev (emp-2) commented on your card 1 "Retry failed webhooks" in {project}: '
        '"Stripe retries for three days."'
    )
    assert (told["project_id"], told["card"]) == (project, 1)
    assert told["created_at"]


def test_reading_notices_in_the_console_leaves_them_for_the_briefing(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, agent = a_board(console, signed_out, "olive-notices-two", 1502)
    dana = a_teammate(console, signed_out, project, "dana-notices-two")
    agent.call("add_card", title="Retry failed webhooks")
    agent.call("claim_card", number=1)
    dana.call("comment_card", number=1, text="Stripe retries for three days.")
    reached = watch_for_writes(monkeypatch)

    first, again = notices(signed_out), notices(signed_out)
    briefed = added_context(agent.start())
    after = notices(signed_out)

    assert first == again and len(first) == 1, "the console doesn't use a notice up"
    assert "commented on your card 1" in briefed, "the member's coding agent is still told"
    assert after == first, "and it stays in the console once the agent has been told"
    assert "commented on your card 1" not in added_context(agent.start()), "which the agent is, once"
    assert reached == []


def test_notices_are_newest_first_and_only_the_members_own(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-notices-three", 1503)
    a_teammate(console, signed_out, project, "dana-notices-three")
    agent.call("add_card", title="Retry failed webhooks")
    agent.call("add_card", title="Upgrade the Stripe client")
    agent.call("update_card", number=1, assignee="emp-2")
    agent.call("update_card", number=1, column="blocked", blocked_reason="Needs the new client.", waits_on=2)
    hers = signed_in(console, "dana-notices-three", 1504)

    agent.call("update_card", number=2, column="done")
    told = notices(hers)

    assert [(one["project_id"], one["card"]) for one in told] == [(project, 1), (project, 1)]
    assert "is done: your card 1" in told[0]["text"], "the card that can go on, not the one that was done"
    assert "assigned card 1" in told[1]["text"]
    assert notices(signed_out) == []
    hers.close()


def test_a_notice_about_a_deleted_card_names_its_board_only(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_board(console, signed_out, "olive-notices-four", 1505)
    dana = a_teammate(console, signed_out, project, "dana-notices-four")
    saved(dana, FLAKY_UPLOADS)
    (number,) = [one["number"] for one in dana.call("board")["columns"]["to_do"] if one["known_issues"]]

    dana.call("delete_card", number=number)
    (told,) = notices(signed_out)

    assert "deleted card" in told["text"]
    assert (told["project_id"], told["card"]) == (project, None)


def test_an_old_notice_leaves_the_console_once_the_agent_has_been_told(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, agent = a_board(console, signed_out, "olive-notices-five", 1506)
    dana = a_teammate(console, signed_out, project, "dana-notices-five")
    agent.call("add_card", title="Retry failed webhooks")
    agent.call("claim_card", number=1)
    dana.call("comment_card", number=1, text="Stripe retries for three days.")

    console.clock.advance(days=8)
    console.github.as_(1506, "olive-notices-five")
    signed_out.sign_in()  # the console's own session ran out in that week
    waiting = notices(signed_out)
    agent.start()

    assert len(waiting) == 1, "however old, it stays until the member's coding agent has had it"
    assert notices(signed_out) == []


def test_notices_need_a_sign_in(console: Console) -> None:
    stranger = console.client()

    assert stranger.get("/api/notices").status_code == 401
    stranger.close()
