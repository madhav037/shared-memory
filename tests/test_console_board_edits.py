"""Changing a project's board from the console: adding, editing, moving, claiming, commenting on and deleting cards,
through the console's JSON API under the same rules the board tools follow (ADR-0014), a refusal saying why."""

from __future__ import annotations

from typing import Any

import httpx

from tests.support import Console, ConsoleClient, Session, add, signed_in
from tests.test_console_board import a_board, board, in_column
from tests.test_known_issues import FLAKY_UPLOADS, saved


def change(client: ConsoleClient, project: str, what: str, body: dict[str, Any] | None = None) -> httpx.Response:
    return client.post_json(f"/api/projects/{project}/{what}", body or {})


def changed(client: ConsoleClient, project: str, what: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """A change the console makes, which is expected to go through."""
    response = change(client, project, what, body)
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def refused(response: httpx.Response) -> str:
    assert response.status_code == 403, response.text
    message: str = response.json()["message"]
    return message


def on_the_board(agent: Session, number: int) -> dict[str, Any]:
    """A card in To do as the member's coding agent reads it."""
    (card,) = [one for one in agent.call("board")["columns"]["to_do"] if one["number"] == number]
    found: dict[str, Any] = card
    return found


def test_a_member_adds_a_card_from_the_console(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_board(console, signed_out, "olive-edits-one", 1401)

    card = changed(
        signed_out,
        project,
        "cards",
        {
            "title": "Retry failed webhooks",
            "description": "Stripe retries for three days; we give up after one.",
            "priority": "high",
            "labels": ["billing"],
            "due_date": "2026-10-15",
        },
    )

    assert card["number"] == 1
    assert (card["column"], card["priority"], card["labels"], card["due_date"]) == (
        "to_do", "high", ["billing"], "2026-10-15",
    )  # fmt: skip
    assert (card["creator"], card["creator_name"], card["assignee"]) == ("E1001", "Olive Owner", None)
    assert in_column(board(signed_out, project), "to_do") == ["Retry failed webhooks"]


def test_a_card_without_a_title_is_refused_with_the_reason(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_board(console, signed_out, "olive-edits-two", 1402)

    assert refused(change(signed_out, project, "cards", {"title": "  "})) == "A card needs a title."
    assert change(signed_out, project, "cards", {}).status_code == 422


def test_a_member_edits_a_cards_fields(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-three", 1403)
    agent.call("add_card", title="Retry webhooks", labels=["billing"])

    card = changed(
        signed_out,
        project,
        "cards/1",
        {
            "title": "Retry failed webhooks",
            "description": "Give up after three days, as Stripe does.",
            "priority": "low",
            "labels": ["billing", "stripe"],
            "due_date": "2026-11-01",
        },
    )
    cleared = changed(signed_out, project, "cards/1", {"due_date": ""})

    assert (card["title"], card["description"], card["priority"], card["labels"], card["due_date"]) == (
        "Retry failed webhooks", "Give up after three days, as Stripe does.", "low", ["billing", "stripe"],
        "2026-11-01",
    )  # fmt: skip
    assert (cleared["title"], cleared["due_date"]) == ("Retry failed webhooks", None), "only what is given changes"
    assert agent.call("board")["labels"] == ["billing", "stripe"]


def test_a_card_moves_between_columns_and_within_one(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-four", 1404)
    for title in ("Retry failed webhooks", "Split the invoice module", "Drop the legacy exporter"):
        agent.call("add_card", title=title)

    changed(signed_out, project, "cards/1/move", {"column": "doing"})
    changed(signed_out, project, "cards/3/move", {"column": "doing"})
    moved = changed(signed_out, project, "cards/3/move", {"column": "doing", "position": 1})
    shown = board(signed_out, project)

    assert (moved["column"], moved["position"]) == ("doing", 1)
    assert in_column(shown, "doing") == ["Drop the legacy exporter", "Retry failed webhooks"]
    assert in_column(shown, "to_do") == ["Split the invoice module"]


def test_a_card_moves_to_blocked_only_with_a_reason(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-five", 1405)
    agent.call("add_card", title="Retry failed webhooks")
    agent.call("add_card", title="Upgrade the Stripe client")

    without = change(signed_out, project, "cards/1/move", {"column": "blocked"})
    blocked = changed(
        signed_out,
        project,
        "cards/1/move",
        {"column": "blocked", "blocked_reason": "Needs the new Stripe client.", "waits_on": 2},
    )

    assert refused(without) == "Moving a card to Blocked needs a reason: say what it is waiting for."
    assert (blocked["column"], blocked["blocked_reason"], blocked["waits_on"]) == (
        "blocked", "Needs the new Stripe client.", 2,
    )  # fmt: skip


def test_a_member_claims_a_card_and_a_second_claim_names_who_has_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-six", 1406)
    agent.call("add_card", title="Retry failed webhooks")
    add(signed_out, "emp-2", "Dana Dev", "dana-edits-six")
    dana = signed_in(console, "dana-edits-six", 1407)

    claimed = changed(dana, project, "cards/1/claim")
    again = change(signed_out, project, "cards/1/claim")

    assert (claimed["column"], claimed["assignee"], claimed["assignee_name"]) == ("doing", "emp-2", "Dana Dev")
    assert "already claimed by" in refused(again) and "emp-2" in refused(again)
    dana.close()


def test_anyone_on_the_project_comments_but_only_the_assignee_changes_their_card(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-seven", 1408)
    agent.call("add_card", title="Retry failed webhooks")
    agent.call("claim_card", number=1)
    add(signed_out, "emp-2", "Dana Dev", "dana-edits-seven")
    dana = signed_in(console, "dana-edits-seven", 1409)

    commented = changed(dana, project, "cards/1/comment", {"text": "Stripe's docs say three days."})
    edit = change(dana, project, "cards/1", {"title": "Mine now"})
    move = change(dana, project, "cards/1/move", {"column": "done"})

    assert [(one["author_name"], one["text"]) for one in commented["comments"]] == [
        ("Dana Dev", "Stripe's docs say three days.")
    ]
    assert "assigned to" in refused(edit)
    assert "assigned to" in refused(move)
    # The board's own refusal names the agent's tool; the console says the same in a member's words.
    assert refused(edit).endswith("Say what you want in a comment instead.")
    assert "comment_card" not in refused(move)
    assert in_column(board(signed_out, project), "doing") == ["Retry failed webhooks"]
    dana.close()


def test_a_card_is_deleted_by_whoever_may_delete_it(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-eight", 1410)
    agent.call("add_card", title="Retry failed webhooks")
    add(signed_out, "emp-2", "Dana Dev", "dana-edits-eight")
    dana = signed_in(console, "dana-edits-eight", 1411)

    not_hers = change(dana, project, "cards/1/delete")
    deleted = changed(signed_out, project, "cards/1/delete")

    assert "only its creator" in refused(not_hers)
    assert deleted == {"number": 1}
    assert all(not column["cards"] for column in board(signed_out, project)["columns"])
    assert "no card 1" in refused(signed_out.get(f"/api/projects/{project}/cards/1"))
    dana.close()


def test_a_card_that_isnt_a_number_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_board(console, signed_out, "olive-edits-nine", 1412)

    assert "isn't a card number" in refused(change(signed_out, project, "cards/twelve/claim"))


def test_a_restricted_projects_board_cant_be_changed_from_outside(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-ten", 1413)
    agent.call("add_card", title="Retry failed webhooks")
    add(signed_out, "emp-2", "Dana Dev", "dana-edits-ten")
    signed_out.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    dana = signed_in(console, "dana-edits-ten", 1414)

    shut_out = [
        change(dana, project, "cards", {"title": "Sneak in"}),
        change(dana, project, "cards/1", {"title": "Renamed"}),
        change(dana, project, "cards/1/move", {"column": "doing"}),
        change(dana, project, "cards/1/claim"),
        change(dana, project, "cards/1/comment", {"text": "Hello"}),
        change(dana, project, "cards/1/delete"),
    ]

    assert all("is restricted" in refused(one) for one in shut_out)
    assert in_column(board(signed_out, project), "to_do") == ["Retry failed webhooks"]
    dana.close()


def test_changing_the_board_needs_the_console_and_a_sign_in(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-eleven", 1415)
    agent.call("add_card", title="Retry failed webhooks")
    stranger = console.client()

    elsewhere = signed_out.post(f"/api/projects/{project}/cards/1/claim", with_header=False)
    signed_out_claim = stranger.post(f"/api/projects/{project}/cards/1/claim")

    assert elsewhere.status_code == 403
    assert signed_out_claim.status_code == 401
    assert in_column(board(signed_out, project), "to_do") == ["Retry failed webhooks"]
    stranger.close()


def test_moving_a_card_to_done_retires_the_known_issue_it_fixes(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-twelve", 1416)
    issue = saved(agent, FLAKY_UPLOADS)
    (number,) = [one["number"] for one in agent.call("board")["columns"]["to_do"] if one["known_issues"]]

    doing = changed(signed_out, project, f"cards/{number}/move", {"column": "doing"})
    done = changed(signed_out, project, f"cards/{number}/move", {"column": "done"})

    assert doing["known_issues_fixed"] == []
    assert done["known_issues_fixed"] == [{"status": "retired", "path": issue, "challenge_id": None, "reason": None}]
    assert agent.call("read", path=issue)["status"] == "retired"


def test_moving_a_card_to_done_asks_another_author_to_retire_their_known_issue(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, _ = a_board(console, signed_out, "olive-edits-thirteen", 1417)
    added = add(signed_out, "emp-2", "Dana Dev", "dana-edits-thirteen")
    dana = Session(console.server, added["personal_token"], project, "billing-api")
    issue = saved(dana, FLAKY_UPLOADS)
    (number,) = [one["number"] for one in dana.call("board")["columns"]["to_do"] if one["known_issues"]]

    (asked,) = changed(signed_out, project, f"cards/{number}/move", {"column": "done"})["known_issues_fixed"]

    assert (asked["status"], asked["path"]) == ("challenge_raised", issue)
    assert isinstance(asked["challenge_id"], int)
    assert dana.call("read", path=issue)["status"] == "active", "its author decides"


def test_a_card_is_added_with_links_to_memories_and_files(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-fourteen", 1418)
    issue = saved(agent, FLAKY_UPLOADS)

    card = changed(
        signed_out,
        project,
        "cards",
        {"title": "Chunk large uploads", "memories": [issue], "files": ["billing-api:src/uploads.py"]},
    )

    assert (card["memories"], card["files"]) == ([issue], ["billing-api:src/uploads.py"])
    assert card["titles"] == {issue: FLAKY_UPLOADS["title"]}
    assert on_the_board(agent, card["number"])["files"] == ["billing-api:src/uploads.py"]


def test_a_cards_links_are_changed_and_taken_off(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-fifteen", 1419)
    issue = saved(agent, FLAKY_UPLOADS)
    agent.call("add_card", title="Chunk large uploads", files=["billing-api:src/uploads.py"])
    (number,) = [one["number"] for one in agent.call("board")["columns"]["to_do"] if not one["known_issues"]]

    linked = changed(
        signed_out,
        project,
        f"cards/{number}",
        {"memories": [issue], "files": ["billing-api:src/uploads.py", "billing-api:README.md"]},
    )
    renamed = changed(signed_out, project, f"cards/{number}", {"title": "Chunk every large upload"})
    cleared = changed(signed_out, project, f"cards/{number}", {"memories": [], "files": []})

    assert (linked["memories"], linked["files"]) == ([issue], ["billing-api:src/uploads.py", "billing-api:README.md"])
    assert (renamed["memories"], renamed["files"]) == (linked["memories"], linked["files"]), "only what is given changes"
    assert (cleared["memories"], cleared["files"]) == ([], [])


def test_a_link_the_board_cant_keep_is_refused_with_the_reason(console: Console, signed_out: ConsoleClient) -> None:
    project, agent = a_board(console, signed_out, "olive-edits-sixteen", 1420)
    agent.call("add_card", title="Chunk large uploads")

    no_repository = change(signed_out, project, "cards", {"title": "Another", "files": ["src/uploads.py"]})
    not_a_memory = change(signed_out, project, "cards/1", {"memories": ["somewhere/else.md"]})
    out_of_reach = change(signed_out, project, "cards/1", {"memories": ["projects/not-this-one/shared/facts/a.md"]})

    assert refused(no_repository) == (
        "File 'src/uploads.py' must be written as repository:path, for example billing-api:package.json."
    )
    assert refused(not_a_memory)
    assert refused(out_of_reach)
    assert on_the_board(agent, 1)["memories"] == []
    assert len(agent.call("board")["columns"]["to_do"]) == 1
