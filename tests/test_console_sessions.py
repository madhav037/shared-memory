"""A project's active sessions in the console: who is working in it, on what, and the files each session holds a lock
on. Read through the console's JSON API under the same reach as the project's board, and read only: nothing the
console can ask changes a session, an activity or a lock (ADR-0009, spec #220)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shared_memory.console_contract import DECLARATIONS
from tests.support import Console, ConsoleClient, Session, add, ask, signed_in, signed_in_owner

RETRY = "src/webhooks/retry.py"
QUEUE = "src/webhooks/queue.py"


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, Session]:
    """A project whose owner is signed in to the console, and a session of the owner's coding agent in it."""
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    return project, owner.in_project(project, "billing-api").as_session("olive-first")


def member_session(client: ConsoleClient, console: Console, project: str, member_id: str, name: str) -> Session:
    """A session of another member's coding agent in the project."""
    token = add(client, member_id, name)["personal_token"]
    return Session(console.server, token).in_project(project, "billing-api").as_session(f"{member_id}-first")


def state(session: Session, activity: str) -> None:
    session.call("set_activity", activity=activity, session=session.identifier)


def take(session: Session, path: str, **more: Any) -> None:
    session.call("take_lock", path=path, session=session.identifier, **more)


def sessions(client: ConsoleClient, project: str) -> list[dict[str, Any]]:
    shown = ask(client, f"/api/projects/{project}/sessions")
    assert shown["project_id"] == project
    found: list[dict[str, Any]] = shown["sessions"]
    return found


def at(moment: str) -> datetime:
    return datetime.fromisoformat(moment)


def test_a_projects_active_sessions_come_back_with_who_what_and_the_files_they_hold(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-one", 1401)
    olive = olive.as_agent("claude-code")
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, "Retrying failed webhooks")
    console.clock.advance(minutes=2)
    take(olive, RETRY)
    console.clock.advance(minutes=1)
    take(olive, QUEUE, repository="billing-web")
    console.clock.advance(minutes=2)
    dana.start()
    console.clock.advance(minutes=1)
    take(olive, RETRY)

    shown = ask(signed_out, f"/api/projects/{project}/sessions")
    first, second = shown["sessions"]

    assert (shown["project_id"], shown["project_name"]) == (project, "Billing")
    assert (first["member_id"], first["member_name"]) == ("E1001", "Olive Owner")
    assert (first["agent"], first["repository"]) == ("Claude Code", "billing-api")
    assert (first["activity"], first["from_card"]) == ("Retrying failed webhooks", False)
    assert (at(first["last_seen_at"]) - at(first["started_at"])).total_seconds() == 6 * 60
    assert [(one["repository"], one["path"]) for one in first["locks"]] == [
        ("billing-api", RETRY),
        ("billing-web", QUEUE),
    ]
    retry = first["locks"][0]
    assert (at(retry["taken_at"]) - at(first["started_at"])).total_seconds() == 2 * 60
    assert retry["last_used_at"] == first["last_seen_at"]
    assert (second["member_id"], second["member_name"]) == ("emp-2", "Dana Dev")
    assert second["agent"] is None, "a session known only by its hooks has not said which coding agent it runs in"
    assert (second["activity"], second["from_card"], second["locks"]) == (None, False, [])
    assert at(second["started_at"]) > at(first["started_at"]), "the oldest session comes first"


def test_a_session_that_ended_or_went_idle_is_not_among_them(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-two", 1402)
    ending, idling = olive.as_session("ending"), olive.as_session("idling")
    for each in (olive, ending, idling):
        each.start()
        take(each, f"src/{each.identifier}.py")
    before = sessions(signed_out, project)

    ending.end()
    console.clock.advance(minutes=20)
    olive.prompt("Carry on.")
    console.clock.advance(minutes=11)
    after = sessions(signed_out, project)

    assert len(before) == 3
    assert [[lock["path"] for lock in one["locks"]] for one in after] == [["src/olive-first.py"]]


def test_a_session_that_stated_no_activity_shows_its_members_card_in_doing(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-three", 1403)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    olive.call("add_card", title="Split the invoice module")
    olive.call("claim_card", number=1)
    olive.start()
    dana.start()
    from_card = sessions(signed_out, project)

    state(olive, "Moving invoices out of the billing module")
    stated = sessions(signed_out, project)

    assert [(one["activity"], one["from_card"]) for one in from_card] == [
        ("Split the invoice module", True),
        (None, False),
    ]
    assert (stated[0]["activity"], stated[0]["from_card"]) == ("Moving invoices out of the billing module", False)


def test_a_project_with_no_active_sessions_answers_with_none(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-four", 1404)
    olive.call("add_card", title="Split the invoice module")

    assert sessions(signed_out, project) == []


def test_a_restricted_projects_sessions_stay_inside_its_access_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-five", 1405)
    state(olive, "Retrying failed webhooks")
    take(olive, RETRY)
    add(signed_out, "emp-2", "Dana Dev", "dana-sessions-five")
    signed_out.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    dana = signed_in(console, "dana-sessions-five", 1406)

    shut_out = dana.get(f"/api/projects/{project}/sessions")
    signed_out.post_json(f"/api/projects/{project}/access", {"member_id": "emp-2"})
    let_in = sessions(dana, project)

    assert shut_out.status_code == 403
    assert "is restricted" in shut_out.json()["message"]
    assert "Retrying failed webhooks" not in shut_out.text and RETRY not in shut_out.text
    assert [one["activity"] for one in let_in] == ["Retrying failed webhooks"]
    dana.close()


def test_a_member_of_another_team_is_refused_a_projects_sessions(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-six", 1407)
    state(olive, "Retrying failed webhooks")
    outsider = console.client()
    signed_in_owner(console, outsider, "olive-sessions-elsewhere", 1408)

    refused = outsider.get(f"/api/projects/{project}/sessions")

    assert refused.status_code == 403
    assert "Retrying failed webhooks" not in refused.text
    outsider.close()


def test_a_projects_sessions_ask_to_sign_in_first(console: Console, signed_out: ConsoleClient) -> None:
    project, _ = a_project(console, signed_out, "olive-sessions-seven", 1409)
    stranger = console.client()

    assert stranger.get(f"/api/projects/{project}/sessions").status_code == 401
    stranger.close()


def test_the_console_can_change_no_session_activity_or_lock(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-eight", 1410)
    state(olive, "Retrying failed webhooks")
    take(olive, RETRY)
    about_sessions = [
        one
        for one in DECLARATIONS
        if any(word in f"{one.path} {one.operation_id}" for word in ("session", "activit", "lock"))
    ]

    tried = [signed_out.post(f"/api/projects/{project}/sessions"), signed_out.post(f"/api/projects/{project}/locks")]

    assert [(one.operation_id, one.method, one.changes) for one in about_sessions] == [
        ("project_sessions", "GET", False)
    ]
    assert all(one.status_code in (404, 405) for one in tried), [one.status_code for one in tried]
    (still,) = sessions(signed_out, project)
    assert (still["activity"], [lock["path"] for lock in still["locks"]]) == ("Retrying failed webhooks", [RETRY])
