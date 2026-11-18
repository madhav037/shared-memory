"""Questions from the console (#570, ADR-0028): a member reading a memory asks its author a question, reads the thread,
and answers the questions waiting for them, through the same operations a session's `ask_question` and
`answer_question` use. The console never changes the memory: an answer that means it should change is made in a
session (ADR-0009). Driven through the console's JSON API."""

from __future__ import annotations

import httpx

from shared_memory.console_contract import DECLARATIONS
from tests.support import (
    SERVICES,
    Console,
    ConsoleClient,
    Session,
    add,
    added_context,
    ask,
    promote_now,
    signed_in,
    signed_in_owner,
)
from tests.test_restricted_projects import restricted

QUESTION = "Does this still hold for the refunds service?"
ANSWER = "Yes, refunds were split out with the rest in March."


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session, Session]:
    """A project whose owner, Olive, is signed in to the console, her session in it, and a session of Dana's there."""
    olive = signed_in_owner(console, client, github, account)
    project = olive.call("create_project", name="Billing")["project_id"]
    dana = Session(console.server, add(client, "emp-2", "Dana Dev")["personal_token"])
    return project, olive.in_project(project, "billing-api"), dana.in_project(project, "billing-api")


def ask_about(client: ConsoleClient, path: str, text: str = QUESTION) -> httpx.Response:
    return client.post_json("/api/memory/questions", {"path": path, "text": text})


def answer(client: ConsoleClient, path: str, question_id: int, text: str = ANSWER) -> httpx.Response:
    return client.post_json(f"/api/memory/questions/{question_id}/answer", {"path": path, "text": text})


def briefing(session: Session) -> str:
    return added_context(session.start())


def test_a_member_asks_from_the_console_and_the_authors_next_briefing_carries_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, _, dana = a_project(console, signed_out, "olive-asks", 1601)
    path = promote_now(dana, SERVICES)
    briefing(dana)

    asked = ask_about(signed_out, path)

    assert asked.status_code == 200, asked.text
    shown = asked.json()
    assert shown["path"] == path and shown["open"] == 1 and shown["may_ask"] is True
    (thread,) = shown["threads"]
    assert (thread["asked_by"], thread["asked_by_name"], thread["text"], thread["state"], thread["answers"]) == (
        "E1001",
        "Olive Owner",
        QUESTION,
        "open",
        [],
    )
    told = briefing(dana)
    assert f"Olive Owner (E1001) asked about your memory {path} (question {thread['question_id']})" in told
    assert QUESTION in told
    events = ask(signed_out, "/api/audit", project=project)["events"]
    assert "question_asked" in [event["kind"] for event in events]
    assert QUESTION not in str(events), "the audit log names the question, never its text"


def test_the_questions_waiting_for_a_member_are_listed_and_answered_from_the_console(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, olive, dana = a_project(console, signed_out, "olive-answers", 1602)
    path = promote_now(olive, SERVICES)
    question_id = dana.call("ask_question", path=path, text=QUESTION)["question_id"]
    briefing(dana)

    (waiting,) = ask(signed_out, "/api/questions")["questions"]
    answered = answer(signed_out, path, question_id)

    assert (waiting["question_id"], waiting["path"], waiting["title"], waiting["text"]) == (
        question_id,
        path,
        SERVICES["title"],
        QUESTION,
    )
    assert (waiting["asked_by"], waiting["asked_by_name"]) == ("emp-2", "Dana Dev")
    assert answered.status_code == 200, answered.text
    (thread,) = answered.json()["threads"]
    assert thread["state"] == "answered"
    assert [(one["by"], one["by_name"], one["text"]) for one in thread["answers"]] == [
        ("E1001", "Olive Owner", ANSWER)
    ]
    told = briefing(dana)
    assert f"Olive Owner (E1001) answered your question {question_id} about {path}" in told and ANSWER in told
    assert ask(signed_out, "/api/questions")["questions"] == [], "an answered question waits no longer"


def test_a_memorys_threads_are_read_with_it_and_its_author_is_not_offered_to_ask(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, olive, dana = a_project(console, signed_out, "olive-reads-threads", 1603)
    path = promote_now(olive, SERVICES)
    question_id = dana.call("ask_question", path=path, text=QUESTION)["question_id"]
    olive.call("answer_question", question_id=question_id, text=ANSWER)

    shown = ask(signed_out, "/api/memory/questions", path=path)
    refused = ask_about(signed_out, path)

    assert (shown["open"], shown["may_ask"]) == (0, False)
    assert [(one["text"], [each["text"] for each in one["answers"]]) for one in shown["threads"]] == [
        (QUESTION, [ANSWER])
    ]
    assert refused.status_code == 403 and "your own memory" in refused.json()["message"]


def test_a_member_kept_out_of_a_restricted_project_neither_reads_nor_asks_about_its_memory(
    console: Console, signed_out: ConsoleClient
) -> None:
    kept_out = restricted(console, signed_out, "olive-restricts-questions", 1604)
    path = promote_now(kept_out.owner.in_project(kept_out.billing, "billing-api"), SERVICES)
    dana = signed_in(console, "dana-olive-restricts-questions", 1605)

    read = dana.get(f"/api/memory/questions?path={path}")
    asked = ask_about(dana, path)

    assert (read.status_code, asked.status_code) == (403, 403)
    assert ask(signed_out, "/api/memory/questions", path=path)["threads"] == []
    dana.close()


def test_questions_ask_to_sign_in_first(console: Console) -> None:
    stranger = console.client()

    assert stranger.get("/api/questions").status_code == 401
    assert stranger.get("/api/memory/questions?path=team/anything.md").status_code == 401
    stranger.close()


def test_the_console_asks_and_answers_questions_and_nothing_more_about_them() -> None:
    """ADR-0028 lets the console ask and answer; it never closes, passes on or removes a question itself."""
    about_questions = sorted(
        (one.operation_id, one.method, one.changes) for one in DECLARATIONS if "question" in one.path
    )

    assert about_questions == [
        ("answer_question", "POST", True),
        ("ask_question", "POST", True),
        ("memory_questions", "GET", False),
        ("questions_waiting", "GET", False),
    ]

