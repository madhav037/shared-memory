"""Questions (#568): a member's session asks a memory's author about that memory, and the author's session answers.

The question reaches the author's next briefing and the answer the asker's; the answers form a thread on the memory
that anyone who can read the memory reads with it, and nobody else. Each question and answer is in the audit log."""

from __future__ import annotations

from typing import Any

import psycopg

from tests.support import (
    SERVICES,
    Console,
    ConsoleClient,
    Session,
    Team,
    add,
    added_context,
    promote_now,
    unfenced_in,
)
from tests.test_restricted_projects import restricted

QUESTION = "Does this still hold for the refunds service?"
ANSWER = "Yes, refunds were split out with the rest in March."


def briefing(session: Session) -> str:
    """What the member's next session starts with."""
    return added_context(session.start())


def ask(session: Session, path: str, text: str = QUESTION) -> dict[str, Any]:
    asked: dict[str, Any] = session.call("ask_question", path=path, text=text)
    return asked


def answer(session: Session, question_id: int, text: str = ANSWER) -> dict[str, Any]:
    answered: dict[str, Any] = session.call("answer_question", question_id=question_id, text=text)
    return answered


def threads(session: Session, path: str) -> dict[str, Any]:
    """The questions on a memory, as a read of it gives them, in the member's own words."""
    read: dict[str, Any] = unfenced_in(session.call("read", path=path))
    questions: dict[str, Any] = read["questions"]
    return questions


def test_a_question_reaches_the_authors_next_briefing(owner: Session, dana: Session) -> None:
    path = promote_now(owner, SERVICES)
    briefing(owner)

    asked = ask(dana, path)

    told = briefing(owner)
    assert asked["question_id"] > 0 and asked["author"] == "owner-1"
    assert f"Dana Dev (emp-2) asked about your memory {path} (question {asked['question_id']})" in told
    assert QUESTION in told and "answer_question" in told
    assert QUESTION not in briefing(owner), "a question is told once"


def test_an_answer_reaches_the_askers_next_briefing(owner: Session, dana: Session) -> None:
    path = promote_now(owner, SERVICES)
    asked = ask(dana, path)
    briefing(dana)

    answer(owner, asked["question_id"])

    told = briefing(dana)
    assert f"Olive Owner (owner-1) answered your question {asked['question_id']} about {path}" in told
    assert ANSWER in told


def test_anyone_who_can_read_the_memory_reads_its_thread(owner: Session, dana: Session, cole: Session) -> None:
    path = promote_now(owner, SERVICES)
    asked = ask(dana, path)
    answer(owner, asked["question_id"])

    read = threads(cole, path)

    assert read["open"] == 0
    (thread,) = read["threads"]
    assert thread["question_id"] == asked["question_id"]
    assert thread["asked_by"] == "Dana Dev (emp-2)" and thread["text"] == QUESTION and thread["state"] == "answered"
    assert [(each["by"], each["text"]) for each in thread["answers"]] == [("Olive Owner (owner-1)", ANSWER)]


def test_a_question_stays_open_until_someone_but_its_asker_answers(owner: Session, dana: Session) -> None:
    path = promote_now(owner, SERVICES)
    asked = ask(dana, path)

    answer(dana, asked["question_id"], "To be clear: I mean the refunds worker, not the API.")
    still_open = threads(owner, path)
    answer(owner, asked["question_id"])

    assert still_open["open"] == 1 and still_open["threads"][0]["state"] == "open"
    assert threads(owner, path)["open"] == 0


def test_a_follow_up_from_the_asker_reaches_the_author(owner: Session, dana: Session) -> None:
    path = promote_now(owner, SERVICES)
    asked = ask(dana, path)
    briefing(owner)

    answer(dana, asked["question_id"], "To be clear: I mean the refunds worker, not the API.")

    told = briefing(owner)
    assert f"Dana Dev (emp-2) answered question {asked['question_id']} about your memory {path}" in told
    assert "the refunds worker" in told


def test_a_memory_with_no_questions_reads_with_none(owner: Session) -> None:
    path = promote_now(owner, SERVICES)

    assert threads(owner, path) == {"open": 0, "threads": []}


def test_asking_about_your_own_memory_is_refused(owner: Session) -> None:
    path = promote_now(owner, SERVICES)

    refused = owner.refusal("ask_question", path=path, text=QUESTION)

    assert "your own memory" in refused


def test_an_empty_question_or_answer_is_refused(owner: Session, dana: Session) -> None:
    path = promote_now(owner, SERVICES)
    asked = ask(dana, path)

    assert "can't be empty" in dana.refusal("ask_question", path=path, text="  ")
    assert "can't be empty" in owner.refusal("answer_question", question_id=asked["question_id"], text="")


def test_answering_a_question_that_does_not_exist_is_refused(owner: Session) -> None:
    refused = owner.refusal("answer_question", question_id=987654, text=ANSWER)

    assert "no question 987654" in refused


def test_asking_about_a_memory_that_does_not_exist_is_refused(dana: Session, project: str) -> None:
    refused = dana.refusal("ask_question", path=f"projects/{project}/shared/conventions/nothing-here.md", text=QUESTION)

    assert refused


def test_each_question_and_answer_is_in_the_audit_log_without_its_text(
    team: Team, owner: Session, dana: Session
) -> None:
    path = promote_now(owner, SERVICES)
    asked = ask(dana, path)
    answer(owner, asked["question_id"])

    with psycopg.connect(team.server.settings.database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT kind, actor, target, detail->>'question_id' FROM audit_events"
            " WHERE project_id = %s AND kind IN ('question_asked', 'question_answered') ORDER BY id",
            (owner.project or "",),
        ).fetchall()

    question_id = str(asked["question_id"])
    assert [tuple(row) for row in rows] == [
        ("question_asked", "emp-2", path, question_id),
        ("question_answered", "owner-1", path, question_id),
    ]
    assert QUESTION not in str(rows) and ANSWER not in str(rows)


def test_a_restricted_projects_questions_are_hidden_from_members_outside_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-questions", 821)
    cole = Session(console.server, add(signed_out, "emp-3", "Cole Coder", "cole-questions")["personal_token"])
    allowed = signed_out.post_json(f"/api/projects/{it.billing}/access", {"member_id": "emp-3"})
    assert allowed.status_code == 200, allowed.text
    in_billing = it.owner.in_project(it.billing, "billing-api")
    path = promote_now(in_billing, SERVICES)
    asked = ask(cole.in_project(it.billing, "billing-api"), path)
    outside = it.dana.in_project(it.billing, "billing-api")

    refusals = [
        outside.refusal("ask_question", path=path, text=QUESTION),
        outside.refusal("answer_question", question_id=asked["question_id"], text=ANSWER),
        outside.refusal("read", path=path),
    ]

    assert all("is restricted" in refusal for refusal in refusals)
    assert threads(in_billing, path)["open"] == 1


# Passed on (#569): a question its author leaves unanswered for 7 days, or whose author has been removed, also goes to
# the memory's project leads, or the team's admins for team memory. Worked out from the clock when questions are read.
# Dana leads no project, so her memory is a convention: an architecture memory would wait on a foundation's keeper.
RETRIES = {
    "title": "Webhooks retry three times",
    "summary": "A failed webhook is retried three times, a minute apart.",
    "type": "convention",
    "body": "Retry a failed webhook three times, one minute apart, then mark it failed and alert the on-call.",
}


def test_a_question_unanswered_for_seven_days_reaches_the_projects_leads(
    team: Team, owner: Session, dana: Session, cole: Session
) -> None:
    path = promote_now(dana, RETRIES)
    asked = ask(cole, path)
    briefing(owner)

    team.server.clock.advance(days=6, hours=23)
    too_soon = briefing(owner)
    team.server.clock.advance(hours=1)
    told = briefing(owner)

    assert QUESTION not in too_soon
    assert f"Cole Coder (emp-3) asked about {path} (question {asked['question_id']})" in told
    assert "unanswered by its author Dana Dev (emp-2) for 7 days" in told
    assert "a lead of its project" in told and QUESTION in told and "answer_question" in told
    assert QUESTION not in briefing(owner), "a question is passed on once"


def test_a_team_memorys_unanswered_question_reaches_the_teams_admins(
    team: Team, owner: Session, dana: Session, cole: Session
) -> None:
    path = promote_now(dana, SERVICES, level="team")
    asked = ask(cole, path)

    team.server.clock.advance(days=7)
    told = briefing(owner)

    assert f"(question {asked['question_id']})" in told and QUESTION in told
    assert "one of the team's admins" in told


def test_a_removed_authors_question_reaches_the_leads_at_once(owner: Session, dana: Session, cole: Session) -> None:
    path = promote_now(dana, RETRIES)
    asked = ask(cole, path)
    briefing(owner)

    owner.call("remove_member", member_id="emp-2")
    told = briefing(owner)

    assert f"(question {asked['question_id']})" in told and QUESTION in told
    assert "its author Dana Dev (emp-2) has been removed" in told


def test_the_author_can_still_answer_once_it_has_been_passed_on(
    team: Team, owner: Session, dana: Session, cole: Session
) -> None:
    path = promote_now(dana, RETRIES)
    asked = ask(cole, path)
    briefing(cole)
    team.server.clock.advance(days=8)
    briefing(owner)

    answered = answer(dana, asked["question_id"])

    assert answered["state"] == "answered"
    assert threads(cole, path)["open"] == 0
    assert ANSWER in briefing(cole)


def test_an_answered_question_is_not_passed_on(team: Team, owner: Session, dana: Session, cole: Session) -> None:
    path = promote_now(dana, RETRIES)
    asked = ask(cole, path)
    answer(dana, asked["question_id"])
    briefing(owner)

    team.server.clock.advance(days=8)

    assert QUESTION not in briefing(owner)
