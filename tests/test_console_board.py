"""A project's board in the console: its columns, filters and archive, and one card with its links and comments,
read through the console's JSON API under the same reach as the board itself (ADR-0014)."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, add, ask, signed_in, signed_in_owner
from tests.test_known_issues import FLAKY_UPLOADS, in_project_memory, saved


def a_board(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session]:
    """A project whose owner is signed in to the console, and the owner's coding agent working in it."""
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    return project, owner.in_project(project, "billing-api")


def board(client: ConsoleClient, project: str, **filters: Any) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/board", **filters)


def archive(client: ConsoleClient, project: str, **filters: Any) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/board/archive", **filters)


def titles(cards: list[dict[str, Any]]) -> list[str]:
    return [one["title"] for one in cards]


def in_column(shown: dict[str, Any], column: str) -> list[str]:
    return titles(next(one for one in shown["columns"] if one["column"] == column)["cards"])


def test_a_board_shows_its_four_columns_top_first(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-board-one", 1301)
    for title in ("Retry failed webhooks", "Split the invoice module", "Drop the legacy exporter", "Upgrade Postgres"):
        agent.call("add_card", title=title, labels=["billing"])
    agent.call("claim_card", number=2)
    agent.call("update_card", number=3, column="blocked", blocked_reason="Waiting on finance to sign off.")
    agent.call("update_card", number=4, column="done")
    agent.call("update_card", number=1, position=1)

    shown = board(signed_out, project)

    assert shown["project_id"] == project
    assert shown["project_name"] == "Billing"
    assert [(one["column"], one["name"]) for one in shown["columns"]] == [
        ("to_do", "To do"), ("doing", "Doing"), ("blocked", "Blocked"), ("done", "Done"),
    ]  # fmt: skip
    assert in_column(shown, "to_do") == ["Retry failed webhooks"]
    assert in_column(shown, "doing") == ["Split the invoice module"]
    assert in_column(shown, "blocked") == ["Drop the legacy exporter"]
    assert in_column(shown, "done") == ["Upgrade Postgres"]
    assert shown["labels"] == ["billing"]
    doing = shown["columns"][1]["cards"][0]
    assert (doing["number"], doing["assignee"], doing["assignee_name"]) == (2, "E1001", "Olive Owner")
    assert shown["columns"][2]["cards"][0]["blocked_reason"] == "Waiting on finance to sign off."


def test_a_board_narrows_by_assignee_label_and_priority(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-board-two", 1302)
    add(signed_out, "emp-2", "Dana Dev", "dana-board-two")
    agent.call("add_card", title="Retry failed webhooks", labels=["billing"], priority="high")
    agent.call("add_card", title="Split the invoice module", labels=["billing", "cleanup"])
    agent.call("add_card", title="Drop the legacy exporter", labels=["cleanup"], priority="high")
    agent.call("update_card", number=2, assignee="emp-2")

    everything = [title for column in board(signed_out, project)["columns"] for title in titles(column["cards"])]
    by_dana = board(signed_out, project, assignee="emp-2")
    cleanup = board(signed_out, project, label="cleanup")
    urgent_cleanup = board(signed_out, project, label="cleanup", priority="high")

    assert len(everything) == 3
    assert [title for column in by_dana["columns"] for title in titles(column["cards"])] == ["Split the invoice module"]
    assert by_dana["columns"][0]["cards"][0]["assignee_name"] == "Dana Dev"
    assert in_column(cleanup, "to_do") == ["Split the invoice module", "Drop the legacy exporter"]
    assert in_column(urgent_cleanup, "to_do") == ["Drop the legacy exporter"]
    assert cleanup["labels"] == ["billing", "cleanup"], "the labels to filter by are the whole board's"


def test_a_card_done_more_than_14_days_ago_is_in_the_archive(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-board-three", 1303)
    for title in ("Retry failed webhooks", "Split the invoice module", "Upgrade Postgres"):
        agent.call("add_card", title=title, labels=["billing"] if title != "Upgrade Postgres" else [])
    agent.call("update_card", number=1, column="done")
    console.clock.advance(days=1)
    agent.call("update_card", number=3, column="done")
    console.clock.advance(days=20)
    agent.call("update_card", number=2, column="done")
    signed_out.sign_in()  # three weeks on, the console session has long run out

    shown = board(signed_out, project)
    archived = archive(signed_out, project)
    archived_billing = archive(signed_out, project, label="billing")

    assert in_column(shown, "done") == ["Split the invoice module"]
    assert archived["project_id"] == project
    assert titles(archived["cards"]) == ["Upgrade Postgres", "Retry failed webhooks"]
    assert titles(archived_billing["cards"]) == ["Retry failed webhooks"]


def test_a_card_reads_whole_with_its_links_and_comments(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-board-four", 1304)
    convention = in_project_memory(
        agent,
        {
            "title": "Use pnpm, not npm",
            "summary": "Every package is managed with pnpm.",
            "type": "convention",
            "body": "We use pnpm for every package; npm writes a second lockfile.",
        },
    )
    issue = saved(agent, FLAKY_UPLOADS)
    cards = [one for column in board(signed_out, project)["columns"] for one in column["cards"]]
    number = next(one["number"] for one in cards if one["known_issues"])
    agent.call(
        "update_card",
        number=number,
        description="Uploads need chunking.",
        memories=[convention],
        files=["billing-api:src/uploads.ts"],
        due_date="2026-10-15",
        column="blocked",
        blocked_reason="Waiting on the proxy team.",
    )
    agent.call("comment_card", number=number, text="The proxy team says next sprint.")

    card = ask(signed_out, f"/api/projects/{project}/cards/{number}")

    assert card["number"] == number
    assert card["description"] == "Uploads need chunking."
    assert card["column"] == "blocked"
    assert card["blocked_reason"] == "Waiting on the proxy team."
    assert card["due_date"] == "2026-10-15"
    assert (card["creator"], card["creator_name"]) == ("E1001", "Olive Owner")
    assert card["memories"] == [convention]
    assert card["known_issues"] == [issue]
    assert card["files"] == ["billing-api:src/uploads.ts"]
    assert card["titles"] == {convention: "Use pnpm, not npm", issue: FLAKY_UPLOADS["title"]}
    assert [(one["author_name"], one["text"]) for one in card["comments"]] == [
        ("Olive Owner", "The proxy team says next sprint.")
    ]


def test_a_card_that_isnt_on_the_board_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_board(console, signed_out, "olive-board-five", 1305)

    missing = signed_out.get(f"/api/projects/{project}/cards/7")

    assert missing.status_code == 403
    assert "no card 7" in missing.json()["message"]


def test_a_restricted_projects_board_stays_inside_its_access_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, agent = a_board(console, signed_out, "olive-board-six", 1306)
    agent.call("add_card", title="Retry failed webhooks")
    add(signed_out, "emp-2", "Dana Dev", "dana-board-six")
    signed_out.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    dana = signed_in(console, "dana-board-six", 1307)

    shut_out = [
        dana.get(f"/api/projects/{project}/board"),
        dana.get(f"/api/projects/{project}/board/archive"),
        dana.get(f"/api/projects/{project}/cards/1"),
    ]
    signed_out.post_json(f"/api/projects/{project}/access", {"member_id": "emp-2"})
    let_in = board(dana, project)

    assert [one.status_code for one in shut_out] == [403, 403, 403]
    assert all("is restricted" in one.json()["message"] for one in shut_out)
    assert in_column(let_in, "to_do") == ["Retry failed webhooks"]
    dana.close()


def test_the_board_asks_to_sign_in_first(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_board(console, signed_out, "olive-board-seven", 1308)
    stranger = console.client()

    assert stranger.get(f"/api/projects/{project}/board").status_code == 401
    assert stranger.get(f"/api/projects/{project}/cards/1").status_code == 401
    stranger.close()
