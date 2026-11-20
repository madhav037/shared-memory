"""Written from your interview (#621, spec #614, ADR-0029): an interviewee sees in the console each memory they author
whose source is an interview, with who interviewed them and when, and retires any of it there, which is governance
(ADR-0009). Driven through the console's JSON API."""

from __future__ import annotations

from typing import Any

from shared_memory.console_contract import DECLARATIONS
from tests.support import Console, ConsoleClient, Session, add, added_context, ask, signed_in, signed_in_owner

CENTS = {
    "title": "Money amounts",
    "summary": "Money is integer cents.",
    "type": "convention",
    "body": "All money amounts are stored as integer cents, never floats.",
}
INTERVIEW = "interview:Billing with Dana"


def interviewed(client: ConsoleClient) -> list[dict[str, Any]]:
    memories: list[dict[str, Any]] = ask(client, "/api/interviewed")["memories"]
    return memories


def interview(owner: Session, memory: dict[str, str], source: str = INTERVIEW, author: str = "emp-2") -> str:
    """Promote a memory cut from an interview, the interviewee as author, keeping both with anything similar."""
    personal = owner.call("remember", **memory)["path"]
    result = owner.call("promote", path=personal, level="project", author=author, imported_from=source)
    if result["status"] == "similar_memories":
        keep_both = {one["path"]: "keep_both" for one in result["similar"]}
        result = owner.call("promote", path=personal, level="project", reference=result["reference"], resolutions=keep_both)
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def a_project_with_dana(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[Session, Session]:
    """The owner signed in, with a project and a session in it, and Dana a member with a session there too."""
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    token = add(client, "emp-2", "Dana Dev", github=f"dana-{github}")["personal_token"]
    return owner.in_project(project, "billing-api"), Session(console.server, token).in_project(project, "billing-api")


def test_an_interviewee_sees_each_memory_from_their_interview_with_interviewer_and_date(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, _ = a_project_with_dana(console, signed_out, "olive-interviews", 8101)
    path = interview(owner, CENTS)
    # An import in Dana's name from a file is not from an interview.
    interview(owner, {**CENTS, "title": "Refunds", "body": "Refunds go back to the card."}, "billing-api:CLAUDE.md")

    (memory,) = interviewed(signed_in(console, "dana-olive-interviews", 8102))

    assert (memory["path"], memory["title"], memory["source"]) == (path, "Money amounts", INTERVIEW)
    assert (memory["interviewer"], memory["interviewer_name"]) == ("E1001", "Olive Owner")
    assert memory["interviewed_at"]


def test_a_member_who_was_not_interviewed_sees_no_list(console: Console, signed_out: ConsoleClient) -> None:
    owner, _ = a_project_with_dana(console, signed_out, "olive-not-interviewed", 8103)
    interview(owner, CENTS)

    assert interviewed(signed_out) == []


def test_an_interviewee_retires_one_and_it_leaves_briefings_and_recall(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, dana = a_project_with_dana(console, signed_out, "olive-interview-retires", 8104)
    path = interview(owner, CENTS)
    owner.call("pin", path=path)
    dana_console = signed_in(console, "dana-olive-interview-retires", 8105)

    retired = dana_console.post_json("/api/memory/retire", {"path": path})

    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "retired"
    assert interviewed(dana_console) == []
    assert "Money amounts" not in added_context(owner.start())
    assert path not in added_context(dana.prompt("how are money amounts stored?"))


def test_the_api_contract_declares_the_interview_list() -> None:
    assert ("/interviewed", "GET") in {(one.path, one.method) for one in DECLARATIONS}
