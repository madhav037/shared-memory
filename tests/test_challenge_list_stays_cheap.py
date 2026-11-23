"""The console's challenge list costs the same however many challenges are open: the masthead asks only for a count,
the list comes a page at a time, each memory a page names is read once, and nothing of a challenging memory its reader
can't reach is sent."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest

from tests.support import (
    Console,
    ConsoleClient,
    Session,
    add,
    ask,
    challenge,
    create,
    promote_keeping_both,
    signed_in,
    signed_in_owner,
)

RULE = {"title": "Invoice numbers", "summary": "Invoices number by year.", "type": "convention",
        "body": "Invoices are numbered by year."}  # fmt: skip


class Transactions:
    def __init__(self) -> None:
        self.count = 0

    def take(self) -> int:
        count, self.count = self.count, 0
        return count


@pytest.fixture
def transactions(console: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Transactions]:
    """How many transactions the server opens."""
    counted = Transactions()
    database = console.server.app.state.database
    opened = database.transaction

    @contextmanager
    def counting() -> Iterator[Any]:
        counted.count += 1
        with opened() as conn:
            yield conn

    monkeypatch.setattr(database, "transaction", counting)
    yield counted


def a_retire_challenge(console: Console, signed_out: ConsoleClient, github: str, account: int) -> int:
    """Erin asks for Dana's project memory to be retired, which waits for the owner too, as the project's lead."""
    signed_in_owner(console, signed_out, github, account)
    project = create(signed_out, "Billing")["project_id"]
    dana, erin = (
        Session(console.server, add(signed_out, member_id, name)["personal_token"]).in_project(project, "billing-api")
        for member_id, name in (("emp-2", "Dana Dev"), ("emp-3", "Erin Dev"))
    )
    raised = erin.call("retire", path=promote_keeping_both(dana, RULE))
    assert raised["status"] == "challenge_raised", raised
    return int(raised["challenge_id"])


def open_as_many(console: Console, challenge_id: int, how_many: int) -> None:
    """More open challenges like this one, as many members' retires of one memory leave."""
    with psycopg.connect(console.server.settings.database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO challenges (team, kind, target_path, target_author, challenger_path, level, raised_by,"
            " promoted_by, raised_at, reasoning, state)"
            " SELECT team, kind, target_path, target_author, challenger_path, level, raised_by, promoted_by, raised_at,"
            " reasoning, state FROM challenges, generate_series(1, %s) WHERE id = %s",
            (how_many, challenge_id),
        )


def test_the_challenge_list_opens_as_many_transactions_for_thirty_open_challenges_as_for_three(
    console: Console, signed_out: ConsoleClient, transactions: Transactions
) -> None:
    challenge_id = a_retire_challenge(console, signed_out, "olive-cheap-list", 9101)
    open_as_many(console, challenge_id, 2)
    transactions.take()
    few = ask(signed_out, "/api/challenges", limit=50)
    for_few = transactions.take()
    open_as_many(console, challenge_id, 27)
    many = ask(signed_out, "/api/challenges", limit=50)
    for_many = transactions.take()

    assert (len(few["waiting"]), len(many["waiting"])) == (3, 30)
    assert for_many == for_few, f"{for_few} transactions for 3 open challenges, {for_many} for 30"


def test_the_count_opens_as_many_transactions_for_thirty_open_challenges_as_for_three(
    console: Console, signed_out: ConsoleClient, transactions: Transactions
) -> None:
    challenge_id = a_retire_challenge(console, signed_out, "olive-cheap-count", 9103)
    open_as_many(console, challenge_id, 2)
    transactions.take()
    few = ask(signed_out, "/api/challenges/count")
    for_few = transactions.take()
    open_as_many(console, challenge_id, 27)
    many = ask(signed_out, "/api/challenges/count")
    for_many = transactions.take()

    assert (few, many) == ({"waiting": 3}, {"waiting": 30})
    assert for_many == for_few


def test_the_list_comes_a_page_at_a_time_oldest_first(console: Console, signed_out: ConsoleClient) -> None:
    challenge_id = a_retire_challenge(console, signed_out, "olive-cheap-pages", 9105)
    open_as_many(console, challenge_id, 24)

    first = ask(signed_out, "/api/challenges")
    second = ask(signed_out, "/api/challenges", after=first["next"])

    assert (len(first["waiting"]), first["total"]) == (20, 25)
    assert first["next"] == first["waiting"][-1]["challenge_id"]
    assert (len(second["waiting"]), second["total"], second["next"]) == (5, 25, None)
    listed = [one["challenge_id"] for one in first["waiting"] + second["waiting"]]
    assert listed == sorted(listed) and listed[0] == challenge_id


def test_the_list_holds_only_the_challenges_against_one_memory_when_asked(
    console: Console, signed_out: ConsoleClient
) -> None:
    challenge_id = a_retire_challenge(console, signed_out, "olive-cheap-one", 9107)
    target = ask(signed_out, "/api/challenges")["waiting"][0]["target"]["path"]

    against = ask(signed_out, "/api/challenges", path=target)
    elsewhere = ask(signed_out, "/api/challenges", path="company/conventions/something-else.md")

    assert [one["challenge_id"] for one in against["waiting"]] == [challenge_id]
    assert (elsewhere["waiting"], elsewhere["total"]) == ([], 0)


def test_a_page_past_its_limit_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-cheap-limit", 9109)

    assert signed_out.get("/api/challenges?limit=101").status_code == 422
    assert signed_out.get("/api/challenges?after=soon").status_code == 422


def test_a_challenge_from_memory_the_decider_cant_reach_is_shown_by_its_number_alone(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-cheap-unseen", 9111)
    billing, payments = create(signed_out, "Billing")["project_id"], create(signed_out, "Payments")["project_id"]
    made = signed_out.post_json("/api/departments", {"name": "Treasury"})
    assert made.status_code == 200, made.text
    treasury = next(one for one in made.json()["departments"] if one["name"] == "Treasury")["department_id"]
    assert signed_out.post_json(f"/api/departments/{treasury}/projects", {"project_id": billing}).status_code == 200
    assert signed_out.post_json(f"/api/departments/{treasury}/restrict", {"restricted": True}).status_code == 200
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev", "dana-cheap-unseen")["personal_token"])
    target = promote_keeping_both(dana.in_project(payments, "payments-api"), RULE, "company")
    raised = challenge(owner.in_project(payments, "payments-api"), {**RULE, "title": "Invoices number by month"},
                       target, "company", reasoning="HIDDEN-REASONING")  # fmt: skip
    # Treasury's memory, which Dana is outside of, stands as the memory offered in its place.
    with psycopg.connect(console.server.settings.database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE challenges SET challenger_path = %s WHERE id = %s",
            (f"departments/{treasury}/conventions/acquisition-plan.md", raised["challenge_id"]),
        )
    browser = signed_in(console, "dana-cheap-unseen", 9112)

    (seen,) = ask(browser, "/api/challenges")["waiting"]

    assert seen["challenge_id"] == raised["challenge_id"]
    assert (seen["challenger"], seen["reasoning"], seen["challenger_unseen"]) == (None, None, True)
    assert "acquisition-plan" not in str(seen) and "HIDDEN-REASONING" not in str(seen)
    browser.close()
