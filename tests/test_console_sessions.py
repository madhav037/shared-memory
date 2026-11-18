"""A project's active sessions in the console: who is working in it, on what, and the files each session holds a lock
on. Read through the console's JSON API under the same reach as the project's board. Nothing the console can ask
changes a session, an activity or a lock (ADR-0009, spec #220); a member may only reply to a message and agree to or
refuse a gate on their own session's work (ADR-0026, #517)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx

from shared_memory.console_api import SAVING
from shared_memory.console_contract import DECLARATIONS
from tests.support import (
    WORKING_FOLDER,
    Console,
    ConsoleClient,
    Session,
    add,
    added_context,
    ask,
    read_tool,
    search_tool,
    signed_in,
    signed_in_owner,
)
from tests.test_messages import ASKED, PROMPT, REPLIED
from tests.test_standby import answer_of, standing_by

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
        ("project_sessions", "GET", False),
        ("recent_sessions", "GET", False),
        ("session_told", "GET", False),
        ("send_message", "POST", True),
        ("answer_gate", "POST", True),
    ], "the only changes are a message and a gate's answer (ADR-0026)"
    assert not SAVING & {"send_message", "answer_gate"}, "neither saves, edits or promotes a memory (ADR-0009)"
    assert all(one.status_code in (404, 405) for one in tried), [one.status_code for one in tried]
    (still,) = sessions(signed_out, project)
    assert (still["activity"], [lock["path"] for lock in still["locks"]]) == ("Retrying failed webhooks", [RETRY])


def test_a_session_shows_the_branch_and_the_files_its_tool_calls_named_but_never_the_tools_or_its_prompts(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-where", 1431)
    olive.prompt("a secret plan for the webhook retries")
    olive.use(read_tool(f"{WORKING_FOLDER}/{QUEUE}"), branch="feature/retries")
    olive.use(search_tool("retries"))
    olive.edit(RETRY)

    (shown,) = sessions(signed_out, project)

    assert shown["branch"] == "feature/retries"
    assert shown["touched_files"] == [RETRY, QUEUE], "the most recent first"
    said = json.dumps(shown)
    assert "a secret plan" not in said
    assert all(tool not in said for tool in ("Read", "Grep", "Edit")), "nor the tools it called"


def test_a_session_whose_hooks_never_named_a_branch_or_a_file_shows_none(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-nowhere", 1432)
    olive.start()

    (shown,) = sessions(signed_out, project)

    assert (shown["branch"], shown["touched_files"]) == (None, [])


def test_a_session_in_a_coding_agent_with_no_hooks_is_marked_as_one_that_cannot_be_gated(
    console: Console, signed_out: ConsoleClient
) -> None:
    """Copilot in VS Code makes tool calls only. Copilot CLI's session is known by the same agent's name, but its hooks
    have called, so it can be gated; so can a Claude Code session, and one that has not said its agent (#518)."""
    project, olive = a_project(console, signed_out, "olive-sessions-unhooked", 1434)
    in_vs_code = olive.as_agent("Visual Studio Code").as_session("vs-code")
    in_the_cli = olive.as_agent("Visual Studio Code").as_session("copilot-cli")
    state(in_vs_code, "Retrying failed webhooks")
    in_the_cli.start(format="copilot-cli")
    state(in_the_cli, "Splitting the invoice module")
    state(olive.as_agent("claude-code").as_session("in-claude-code"), "Moving the cart to the new API")
    olive.as_session("unsaid").start()

    shown = {one["activity"]: one for one in sessions(signed_out, project)}

    assert shown["Retrying failed webhooks"]["agent"] == "GitHub Copilot"
    assert shown["Retrying failed webhooks"]["can_be_gated"] is False
    assert shown["Splitting the invoice module"]["can_be_gated"] is True, "its hooks have called"
    assert shown["Moving the cart to the new API"]["can_be_gated"] is True
    assert shown[None]["can_be_gated"] is True, "its agent is not known"


# Sessions that talk (#516): the project's collisions and gates for every member who can reach it, and the signed-in
# member's own sessions' messages. The same activity scores 1 against itself, so stating it twice collides.

WEBHOOKS = "Retrying failed webhooks"


def page(client: ConsoleClient, project: str) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/sessions")


def test_a_collision_and_the_gate_it_makes_show_who_is_later_who_it_waits_for_and_until_when(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-gate", 1433)
    olive = olive.as_agent("claude-code")
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    console.clock.advance(minutes=1)
    state(dana, WEBHOOKS)
    console.clock.advance(minutes=2)

    shown = page(signed_out, project)

    (collision,) = shown["collisions"]
    assert (collision["later"]["member_id"], collision["earlier"]["member_id"]) == ("emp-2", "E1001")
    assert (collision["earlier"]["agent"], collision["earlier"]["activity"]) == ("Claude Code", WEBHOOKS)
    assert collision["cause"] == "activity"
    (gate,) = shown["gates"]
    assert gate["later"]["member_name"] == "Dana Dev"
    (waits,) = gate["waits_for"]
    assert waits["earlier"]["member_name"] == "Olive Owner"
    assert (at(waits["until"]) - at(collision["found_at"])).total_seconds() == 5 * 60, "the project's wait"
    assert (at(waits["until"]) - at(shown["now"])).total_seconds() == 3 * 60, "the time left"


def test_a_gate_leaves_the_page_when_its_member_says_different_work_or_the_wait_has_passed(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-lifted", 1457)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    cole = member_session(signed_out, console, project, "emp-3", "Cole Coder")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    state(cole, WEBHOOKS)
    before = page(signed_out, project)["gates"]

    dana.call("different_work", session=dana.identifier)
    after_different_work = page(signed_out, project)["gates"]
    console.clock.advance(minutes=5)
    after_the_wait = page(signed_out, project)

    assert [gate["later"]["member_id"] for gate in before] == ["emp-2", "emp-3"]
    assert [gate["later"]["member_id"] for gate in after_different_work] == ["emp-3"]
    assert after_the_wait["gates"] == []
    assert len(after_the_wait["collisions"]) == 3, "the collisions stay while their sessions are active"


def test_a_members_own_two_sessions_collide_but_never_gate_each_other(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-own", 1435)
    state(olive, WEBHOOKS)
    state(olive.as_session("olive-second"), WEBHOOKS)

    shown = page(signed_out, project)

    assert len(shown["collisions"]) == 1
    assert shown["gates"] == []


def test_a_member_sees_their_own_sessions_messages_and_no_one_elses(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-messages", 1436)
    olive.start()
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    cole_token = add(signed_out, "emp-3", "Cole Coder", "cole-sessions-messages")["personal_token"]
    cole = Session(console.server, cole_token).in_project(project, "billing-api").as_session("cole-first")
    dana.start()
    cole.start()
    dana.call("send_message", session=dana.identifier, to="E1001", text="Do you have the retry UI?")
    console.clock.advance(minutes=1)
    olive.call("send_message", session=olive.identifier, to="emp-2", text="Yes, take the back end.")
    cole.call("send_message", session=cole.identifier, to="emp-2", text="Lunch at one?")
    coles_console = signed_in(console, "cole-sessions-messages", 1437)

    olives = page(signed_out, project)["messages"]
    coles = page(coles_console, project)["messages"]

    assert [(one["sender_name"], one["recipient_name"], one["text"], one["sent_by_me"]) for one in olives] == [
        ("Dana Dev", "Olive Owner", "Do you have the retry UI?", False),
        ("Olive Owner", "Dana Dev", "Yes, take the back end.", True),
    ]
    assert olives[0]["delivered_at"] is not None, "Olive's send_message call was told of Dana's message"
    assert olives[1]["delivered_at"] is None, "Dana's session has made no call since"
    assert [one["text"] for one in coles] == ["Lunch at one?"], "only what Cole's own session sent"
    coles_console.close()


def test_reading_messages_on_the_page_leaves_them_waiting_for_the_session(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-unread", 1438)
    olive.start()
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    dana.start()
    dana.call("send_message", session=dana.identifier, to="E1001", text="Do you have the retry UI?")

    page(signed_out, project)
    told = json.dumps(olive.prompt("Carry on."))
    console.clock.advance(minutes=1)
    (delivered,) = page(signed_out, project)["messages"]

    assert "Do you have the retry UI?" in told, "the page read it, and the session was still told"
    assert delivered["delivered_at"] is not None


def test_a_restricted_projects_collisions_gates_and_messages_stay_inside_its_access_list(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-talk-shut", 1439)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    dana.call("send_message", session=dana.identifier, to="E1001", text="Do you have the retry UI?")
    add(signed_out, "emp-3", "Cole Coder", "cole-sessions-talk-shut")
    signed_out.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    cole = signed_in(console, "cole-sessions-talk-shut", 1440)

    shut_out = cole.get(f"/api/projects/{project}/sessions")

    assert shut_out.status_code == 403
    assert WEBHOOKS not in shut_out.text and "retry UI" not in shut_out.text and "Dana Dev" not in shut_out.text
    cole.close()


# Answering from the console (#517, ADR-0026): a member replies to a message and agrees to or refuses a gate on their
# own session's work, through the same operations their session's tools use. The other session hears it on its next
# hook.


def reply(client: ConsoleClient, project: str, to: str, text: str) -> httpx.Response:
    return client.post_json(f"/api/projects/{project}/sessions/messages", {"to": to, "text": text})


def answer(client: ConsoleClient, project: str, gate: str, said: str, text: str | None = None) -> httpx.Response:
    return client.post_json(f"/api/projects/{project}/sessions/gates/{gate}/answer", {"answer": said, "text": text})


def heard(session: Session) -> str:
    """What the session hears on its next tool call, in Claude Code's hook before a tool."""
    return added_context(session.use(search_tool("webhook")))


def gate_events(client: ConsoleClient, project: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/audit?project={project}")
    assert response.status_code == 200, response.text
    return [event for event in response.json()["events"] if event["kind"] in ("gate_agreed", "gate_refused")]


def test_a_reply_from_the_console_reaches_the_other_session_on_its_next_hook(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-reply", 1441)
    olive.start()
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    dana.start()
    dana.call("send_message", session=dana.identifier, to="E1001", text="Do you have the retry UI?")

    replied = reply(signed_out, project, "emp-2", "Yes, take the back end.")
    told = heard(dana)

    assert replied.status_code == 200, replied.text
    assert [(one["text"], one["sent_by_me"]) for one in replied.json()["messages"]] == [
        ("Do you have the retry UI?", False),
        ("Yes, take the back end.", True),
    ]
    assert len({one["message_id"] for one in replied.json()["messages"]}) == 2, "each known by its own number"
    assert "Olive Owner (E1001)" in told and "Yes, take the back end." in told
    assert "Yes, take the back end." not in heard(dana), "heard once"


def test_a_reply_needs_a_session_of_the_members_own_in_the_project(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, _ = a_project(console, signed_out, "olive-console-no-session", 1442)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    dana.start()

    refused = reply(signed_out, project, "emp-2", "Hello?")

    assert refused.status_code == 403
    assert "None of your sessions" in refused.json()["message"]
    assert "Hello?" not in heard(dana)


def test_agreeing_from_the_console_lifts_the_gate_and_the_later_session_hears_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-agree", 1443)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    (gate,) = page(signed_out, project)["gates"]

    agreed = answer(signed_out, project, "emp-2", "agree", "Go ahead, I am only on the docs.")
    told = heard(dana)

    assert [(one["on_my_work"], one["refused"]) for one in gate["waits_for"]] == [(True, False)]
    assert agreed.status_code == 200, agreed.text
    assert agreed.json()["gates"] == []
    assert "Olive Owner (E1001) agreed" in told and "Go ahead, I am only on the docs." in told
    assert dana.edit(RETRY) == {}, "the edit goes ahead"
    (event,) = gate_events(signed_out, project)
    assert (event["kind"], event["actor"], event["target"]) == ("gate_agreed", "E1001", "emp-2")
    assert "docs" not in json.dumps(event), "never the answer's words"


def test_refusing_from_the_console_keeps_the_gate_past_the_wait_and_the_later_session_hears_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-refuse", 1444)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)

    refused = answer(signed_out, project, "emp-2", "refuse", "I am halfway through the retries.")
    told = heard(dana)
    console.clock.advance(minutes=6)
    olive.prompt("Carry on.")
    still = page(signed_out, project)

    assert refused.status_code == 200, refused.text
    assert "Olive Owner (E1001) refused" in told and "halfway through the retries" in told
    (gate,) = still["gates"]
    assert [(one["earlier"]["member_id"], one["refused"]) for one in gate["waits_for"]] == [("E1001", True)]
    assert "[gated]" in json.dumps(dana.edit(RETRY))
    assert [event["kind"] for event in gate_events(signed_out, project)] == ["gate_refused"]


def test_only_the_earlier_sessions_own_member_answers_a_gate_from_the_console(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-not-yours", 1445)
    dana_token = add(signed_out, "emp-2", "Dana Dev", "dana-console-not-yours")["personal_token"]
    dana = Session(console.server, dana_token).in_project(project, "billing-api").as_session("dana-first")
    add(signed_out, "emp-3", "Cole Coder", "cole-console-not-yours")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    danas_console = signed_in(console, "dana-console-not-yours", 1446)
    coles_console = signed_in(console, "cole-console-not-yours", 1447)

    by_the_later_member = answer(danas_console, project, "emp-2", "agree")
    by_another_member = answer(coles_console, project, "emp-2", "agree")
    seen_by_cole = page(coles_console, project)["gates"]

    assert by_the_later_member.status_code == 403 and by_another_member.status_code == 403
    assert "No gate of 'emp-2' waits on your sessions' work" in by_another_member.json()["message"]
    assert [one["on_my_work"] for gate in seen_by_cole for one in gate["waits_for"]] == [False]
    assert "[gated]" in json.dumps(dana.edit(RETRY)), "still gated"
    assert gate_events(signed_out, project) == []
    danas_console.close()
    coles_console.close()


def test_an_answer_is_agree_or_refuse_and_a_gate_that_has_ended_takes_none(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-ended", 1448)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)

    wrong = answer(signed_out, project, "emp-2", "maybe")
    dana.call("different_work", session=dana.identifier)
    too_late = answer(signed_out, project, "emp-2", "refuse")

    assert wrong.status_code == 422
    assert too_late.status_code == 403
    assert dana.edit(RETRY) == {}



# A reply or an answer from the console is the same operation as the session tool's (ADR-0026), and what the member
# did there reaches their own session on its next hook (story 38).


def test_a_reply_from_the_console_answers_the_urgent_message_that_gates_the_members_session(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-urgent", 1449)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    dana.call("send_message", session=dana.identifier, to="E1001", text="Can I take the retries?", urgent=True)
    gated = olive.edit(RETRY)

    replied = reply(signed_out, project, "emp-2", "Yes, take them.")

    assert "[gated]" in json.dumps(gated)
    assert replied.status_code == 200, replied.text
    allowed = olive.edit(RETRY).get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
    assert allowed, "the urgent message is answered, so the edit goes ahead, whatever news its answer carries"


def test_an_urgent_message_shows_as_urgent_on_the_page(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-console-urgent-shown", 1450)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    dana.call("send_message", session=dana.identifier, to="E1001", text="Are you on the retries?")
    dana.call("send_message", session=dana.identifier, to="E1001", text="Please answer.", urgent=True)

    shown = page(signed_out, project)["messages"]

    assert [(one["text"], one["urgent"]) for one in shown] == [
        ("Are you on the retries?", False),
        ("Please answer.", True),
    ]


def test_a_reply_from_the_console_stops_the_recent_work_reminder(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-console-heed", 1451)
    dana_token = add(signed_out, "emp-2", "Dana Dev", "dana-console-heed")["personal_token"]
    dana = Session(console.server, dana_token).in_project(project, "billing-api").as_session("dana-first")
    state(olive, WEBHOOKS)
    olive.end()
    console.clock.advance(minutes=10)
    state(dana, WEBHOOKS)
    reminded = added_context(dana.prompt("Retry the failed webhooks."))
    danas_console = signed_in(console, "dana-console-heed", 1452)

    replied = reply(danas_console, project, "E1001", "I am picking up the retries.")

    assert "[recent work]" in reminded
    assert replied.status_code == 200, replied.text
    assert "[recent work]" not in added_context(dana.prompt("Retry the failed webhooks."))
    danas_console.close()


def test_what_a_member_did_in_the_console_reaches_their_own_session_once(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-own", 1453)
    olive.start()
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    heard(olive)

    answer(signed_out, project, "emp-2", "refuse", "I am halfway through the retries.")
    reply(signed_out, project, "emp-2", "Pick the docs instead?")
    told = heard(olive)

    assert "[console]" in told
    assert "refused Dana Dev (emp-2)" in told and "halfway through the retries" in told
    assert "Pick the docs instead?" in told
    assert "[console]" not in heard(olive), "told once"


def test_a_gate_whose_wait_passed_is_recorded_when_the_page_reads_it(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-console-timeout", 1454)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    console.clock.advance(minutes=6)

    shown = page(signed_out, project)
    response = signed_out.get(f"/api/audit?project={project}")

    assert shown["gates"] == []
    assert response.status_code == 200, response.text
    timed_out = [event for event in response.json()["events"] if event["kind"] == "gate_timed_out"]
    assert [(event["actor"], event["target"]) for event in timed_out] == [("emp-2", "E1001")]


def test_the_handoff_notes_of_sessions_gone_lately_show_on_the_page(console: Console, signed_out: ConsoleClient) -> None:
    project, olive = a_project(console, signed_out, "olive-console-handoff", 1455)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev").as_agent("claude-code")
    state(dana, WEBHOOKS)
    dana.use(read_tool(f"{WORKING_FOLDER}/{RETRY}"), branch="webhook-retries")
    dana.call("leave_handoff_note", session=dana.identifier, done="The retry loop.", left="The settings page.")
    dana.end()
    state(olive, "Tidying the invoices")

    (note,) = page(signed_out, project)["handoff_notes"]

    assert (note["member_name"], note["agent"], note["branch"]) == ("Dana Dev", "Claude Code", "webhook-retries")
    assert (note["done"], note["left"], note["activity"]) == ("The retry loop.", "The settings page.", WEBHOOKS)
    assert note["touched_files"] == [RETRY] and note["by_server"] is False


def test_the_page_is_told_the_longest_reply_and_a_longer_one_is_refused(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-console-limit", 1456)
    olive.start()
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    dana.start()

    limit = page(signed_out, project)["text_limit"]
    too_long = reply(signed_out, project, "emp-2", "x" * (limit + 1))

    assert limit == 2000
    assert too_long.status_code == 422


def test_a_session_standing_by_shows_whose_answer_it_awaits_and_the_mark_goes_when_the_standby_ends(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-standby", 1490)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    before = sessions(signed_out, project)
    held = standing_by(dana)

    during = sessions(signed_out, project)
    read_again = sessions(signed_out, project)
    dana.prompt(PROMPT)
    ended = answer_of(held)
    after = sessions(signed_out, project)

    assert [one["standby"] for one in before] == [None, None]
    olives, danas = during
    assert olives["standby"] is None
    assert danas["member_id"] == "emp-2"
    assert danas["standby"]["awaits"] == [{"member_id": "E1001", "member_name": "Olive Owner"}]
    assert at(danas["standby"]["started_at"]) <= at(danas["standby"]["ends_at"])
    assert read_again[1]["standby"] == danas["standby"], "reading the page leaves the standby held"
    assert ended["ended"] == "moved_on"
    assert [one["standby"] for one in after] == [None, None]


def test_a_session_standing_by_for_no_one_in_particular_awaits_no_member(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-standby-anyone", 1491)
    olive.start()
    held = standing_by(olive)

    (during,) = sessions(signed_out, project)
    olive.prompt(PROMPT)
    answer_of(held)

    assert during["standby"] == {**during["standby"], "awaits": []}


def test_a_session_standing_by_after_an_urgent_message_awaits_its_recipients_answer(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-standby-urgent", 1492)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    state(olive, WEBHOOKS)
    state(dana, WEBHOOKS)
    dana.call("different_work", session=dana.identifier)
    dana.call("send_message", session=dana.identifier, to="E1001", text=ASKED, urgent=True)
    held = standing_by(dana)

    during = sessions(signed_out, project)[1]
    olive.call("send_message", session=olive.identifier, to="emp-2", text=REPLIED)
    answered = answer_of(held)
    held_again = standing_by(dana)
    after_the_answer = sessions(signed_out, project)[1]
    dana.prompt(PROMPT)
    answer_of(held_again)

    assert during["member_id"] == "emp-2"
    assert during["standby"]["awaits"] == [{"member_id": "E1001", "member_name": "Olive Owner"}], (
        "its edit is no longer gated: it awaits the answer to its urgent message"
    )
    assert answered["ended"] == "news"
    assert after_the_answer["standby"]["awaits"] == [], "the urgent message has been answered"


def test_a_session_standing_by_after_a_message_awaits_its_recipients_reply_until_they_reply(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, olive = a_project(console, signed_out, "olive-sessions-standby-message", 1493)
    dana = member_session(signed_out, console, project, "emp-2", "Dana Dev")
    olive.start()
    dana.start()
    dana.call("send_message", session=dana.identifier, to="E1001", text=ASKED)
    held = standing_by(dana)

    during = sessions(signed_out, project)[1]
    olive.call("send_message", session=olive.identifier, to="emp-2", text=REPLIED)
    replied = answer_of(held)
    held_again = standing_by(dana)
    after_the_reply = sessions(signed_out, project)[1]
    dana.prompt(PROMPT)
    answer_of(held_again)

    assert during["member_id"] == "emp-2"
    assert during["standby"]["awaits"] == [{"member_id": "E1001", "member_name": "Olive Owner"}]
    assert replied["ended"] == "news" and REPLIED in replied["message"]
    assert after_the_reply["standby"]["awaits"] == [], "Olive has replied to its latest message"
