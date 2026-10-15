"""The sessions the server knows: started, last seen, ended and idle (ADR-0018)."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess

import httpx
import pytest

from shared_memory.config import Settings
from shared_memory.sessions import Sessions
from tests.support import (
    REPO_ROOT,
    Console,
    ConsoleClient,
    RunningServer,
    Session,
    Team,
    add,
    added_context,
    create,
    signed_in_owner,
)
from tests.test_hooks import CONTEXT_FIELDS

ENDED = "its activity and locks ended"


def active(session: Session) -> list[tuple[str, str]]:
    """Who is active in this session's project: each session's member and its identifier."""
    return [(known.member_id, known.identifier) for known in session.active_sessions()]


def test_a_session_is_active_from_its_start_until_its_end(owner: Session) -> None:
    owner.start()
    started = active(owner)

    owner.end()

    assert started == [("owner-1", "test-session")]
    assert active(owner) == []


def test_a_session_with_no_call_for_the_idle_time_is_no_longer_active(team: Team, owner: Session) -> None:
    owner.start()

    team.server.clock.advance(minutes=29, seconds=59)
    just_before = active(owner)
    team.server.clock.advance(seconds=1)

    assert just_before == [("owner-1", "test-session")]
    assert active(owner) == []


def test_a_prompt_keeps_a_session_active(team: Team, owner: Session) -> None:
    owner.start()

    team.server.clock.advance(minutes=29)
    owner.prompt("write a haiku about cats")
    team.server.clock.advance(minutes=29)

    assert active(owner) == [("owner-1", "test-session")]


def test_a_tool_call_that_names_the_session_keeps_it_active(team: Team, owner: Session) -> None:
    owner.start()

    team.server.clock.advance(minutes=29)
    owner.call("briefing", session=owner.identifier)
    team.server.clock.advance(minutes=29)

    assert active(owner) == [("owner-1", "test-session")]


def test_a_tool_call_that_names_no_session_does_not_keep_one_active(team: Team, owner: Session) -> None:
    owner.start()

    team.server.clock.advance(minutes=29)
    owner.call("tree")
    team.server.clock.advance(minutes=29)

    assert active(owner) == []


def test_two_sessions_of_one_member_in_one_project_are_two_sessions(owner: Session) -> None:
    second = owner.as_session("second-session")
    owner.start()
    second.start()

    owner.end()

    assert active(owner) == [("owner-1", "second-session")]


def test_two_members_sessions_under_one_identifier_are_two_sessions(owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()

    dana.end()

    assert active(owner) == [("owner-1", "test-session")]


def test_a_session_is_known_with_its_member_repository_and_start(team: Team, dana: Session) -> None:
    dana.start()
    team.server.clock.advance(minutes=5)
    dana.prompt("write a haiku about cats")

    (known,) = dana.active_sessions()

    assert (known.member_id, known.member_name) == ("emp-2", "Dana Dev")
    assert (known.project_id, known.repository) == (dana.project, "billing-api")
    assert known.last_seen_at == team.server.clock.now
    assert (known.last_seen_at - known.started_at).total_seconds() == 300


def test_a_session_is_known_by_the_coding_agent_its_tool_calls_come_from(owner: Session) -> None:
    owner.start()
    before = owner.active_sessions()[0].agent

    owner.as_agent("claude-code").call("briefing", session=owner.identifier)

    assert before is None, "a hook does not say which coding agent sent it"
    assert owner.active_sessions()[0].agent == "Claude Code"


def test_a_tool_call_without_the_agents_name_is_known_by_its_user_agent(owner: Session) -> None:
    # An agent on protocol 2025-06-18, as Codex 0.162.1 is, names itself only when it initializes, and this server
    # keeps nothing between requests: its tool calls carry just the User-Agent it sends with every request (#276).
    owner.start()

    response = httpx.post(
        f"{owner.server.url}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "briefing", "arguments": {"session": owner.identifier}},
        },
        headers={
            **owner.headers(),
            "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": "2025-06-18",
            "User-Agent": "codex-mcp-client/0.162.1",
        },
        timeout=30,
    )

    assert response.status_code == 200, response.text
    assert owner.active_sessions()[0].agent == "Codex"


def test_the_briefing_a_session_starts_with_names_its_identifier(owner: Session) -> None:
    session = owner.as_session("0b1f6c2e-session")

    briefing = added_context(session.start())

    assert "0b1f6c2e-session" in briefing
    assert "`session`" in briefing


def test_the_briefing_names_the_repository_its_session_works_in_and_how_to_write_its_files(owner: Session) -> None:
    started = added_context(owner.as_session("repository-named").start())
    fetched = owner.as_session("fetched").call("briefing")

    for briefing in (started, fetched):
        assert f"works in the repository `{owner.repository}`" in briefing
        assert f"`{owner.repository}:package.json`" in briefing


def test_a_session_that_names_no_repository_is_told_none(owner: Session) -> None:
    briefing = added_context(dataclasses.replace(owner, repository=None).as_session("no-repository").start())

    assert "no-repository" in briefing
    assert "works in the repository" not in briefing


def test_the_briefing_tool_without_a_session_starts_one_and_names_it(owner: Session) -> None:
    briefing = owner.call("briefing")

    ((member, identifier),) = active(owner)
    assert member == "owner-1"
    assert identifier in briefing
    assert "nothing is pinned" in briefing


def test_the_briefing_tool_with_a_session_starts_no_other(owner: Session) -> None:
    owner.start()

    briefing = owner.call("briefing", session=owner.identifier)

    assert active(owner) == [("owner-1", "test-session")]
    assert "`test-session`" in briefing


def test_a_session_identifier_too_long_to_keep_is_refused_by_the_tool_and_ignored_by_the_hook(owner: Session) -> None:
    endless = "x" * 500

    refusal = owner.refusal("briefing", session=endless)
    started = owner.as_session(endless).start()

    assert "session" in refusal
    assert endless not in added_context(started)
    assert active(owner) == []


def test_a_session_back_from_idle_is_active_and_told_once_that_its_activity_and_locks_ended(
    team: Team, owner: Session
) -> None:
    owner.start()
    team.server.clock.advance(minutes=31)

    first = added_context(owner.prompt("write a haiku about cats"))
    second = owner.prompt("write a haiku about cats")

    assert ENDED in first
    assert second == {}
    assert active(owner) == [("owner-1", "test-session")]


def test_a_session_back_from_idle_through_a_tool_is_told_on_its_next_prompt(team: Team, owner: Session) -> None:
    owner.start()
    team.server.clock.advance(minutes=31)

    owner.call("briefing", session=owner.identifier)

    assert ENDED in added_context(owner.prompt("write a haiku about cats"))


def test_a_session_that_never_went_idle_is_told_nothing(team: Team, owner: Session) -> None:
    owner.start()
    team.server.clock.advance(minutes=29)

    assert owner.prompt("write a haiku about cats") == {}


def test_a_session_that_starts_again_after_its_end_is_active_and_told_once_that_its_activity_and_locks_ended(
    team: Team, owner: Session
) -> None:
    """Claude Code resuming a session it had ended."""
    owner.start()
    owner.end()
    team.server.clock.advance(minutes=45)

    owner.start()
    first = added_context(owner.prompt("write a haiku about cats"))

    assert active(owner) == [("owner-1", "test-session")]
    assert ENDED in first
    assert "This session ended" in first and "idle" not in first, "in words that fit an end"
    assert owner.prompt("write a haiku about cats") == {}


def test_a_session_whose_next_prompt_follows_its_end_is_told_on_that_prompt(owner: Session, cole: Session) -> None:
    """Cline ends the session when a task completes, and the task may go on."""
    owner.call("set_activity", activity="Retrying failed webhooks", session=owner.identifier)
    owner.call("take_lock", path="src/webhooks/retry.py", session=owner.identifier)
    owner.end()

    back = added_context(owner.prompt("write a haiku about cats"))

    assert ENDED in back and "This session ended" in back
    assert cole.call("take_lock", path="src/webhooks/retry.py", session=cole.identifier)["locked"] is True
    assert owner.prompt("write a haiku about cats") == {}


def test_a_session_back_from_its_end_through_a_tool_is_told_in_that_tools_answer(owner: Session) -> None:
    owner.start()
    owner.end()

    stated = owner.call("set_activity", activity="Retrying failed webhooks", session=owner.identifier)

    assert len(stated["notices"]) == 1 and "This session ended" in stated["notices"][0]
    assert owner.prompt("write a haiku about cats") == {}


def test_a_session_that_ends_again_before_it_was_told_is_told_once(owner: Session) -> None:
    owner.start()
    owner.end()
    owner.start()
    owner.end()

    owner.start()

    assert added_context(owner.prompt("write a haiku about cats")).count("This session ended") == 1
    assert owner.prompt("write a haiku about cats") == {}


def test_the_idle_time_defaults_to_thirty_minutes_and_is_read_from_the_environment() -> None:
    assert Settings.from_env({}).session_idle_minutes == 30
    assert Settings.from_env({"SHARED_MEMORY_SESSION_IDLE_MINUTES": "45"}).session_idle_minutes == 45


@pytest.mark.parametrize("format", list(CONTEXT_FIELDS))
def test_the_session_end_hook_answers_every_family_emptily(owner: Session, format: str | None) -> None:
    owner.start()

    assert owner.end(format=format) == {}
    assert active(owner) == []


def test_the_session_end_hook_never_fails_a_session(team: Team, owner: Session) -> None:
    unknown = Session(team.server, "smt_nope", owner.project, "billing-api")
    never_started = owner.as_session("never-started")
    unreadable = httpx.post(f"{owner.server.url}/hooks/session-end", content=b"not json", headers=owner.headers())

    assert unknown.end() == {}
    assert team.owner().end() == {}, "a session outside any project"
    assert never_started.end() == {}
    assert owner.hook_payload("session-end", {"hook_event_name": "SessionEnd"}) == {}, "a payload naming no session"
    assert (unreadable.status_code, unreadable.json()) == (200, {})


def plugin_hook(event: str) -> str:
    """The command Claude Code's plugin runs for one event."""
    hooks = json.loads((REPO_ROOT / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    ((hook,),) = [entry["hooks"] for entry in hooks[event]]
    assert hook["type"] == "command"
    command: str = hook["command"]
    return command


def test_claude_codes_plugin_posts_its_session_end_to_the_session_end_hook() -> None:
    command = plugin_hook("SessionEnd")

    assert '"$CLAUDE_PLUGIN_OPTION_SERVER_URL/hooks/session-end"' in command
    assert "--max-time" in command
    assert command.endswith("|| true"), "a server that is down never fails the session's end"


@pytest.mark.skipif(
    shutil.which("sh") is None or shutil.which("curl") is None,
    reason="Claude Code runs the plugin's hooks with curl in a POSIX shell, which aren't both here",
)
def test_claude_codes_plugin_ends_the_session_when_claude_code_does(team: Team, owner: Session) -> None:
    owner.start()
    assert owner.project is not None and owner.repository is not None

    ran = subprocess.run(
        ["sh", "-c", plugin_hook("SessionEnd")],
        input=json.dumps({"session_id": owner.identifier, "hook_event_name": "SessionEnd", "reason": "other"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "CLAUDE_PLUGIN_OPTION_SERVER_URL": team.server.url,
            "CLAUDE_PLUGIN_OPTION_PERSONAL_TOKEN": team.owner_token,
            "SHARED_MEMORY_PROJECT": owner.project,
            "SHARED_MEMORY_REPOSITORY": owner.repository,
        },
    )

    assert ran.returncode == 0, ran.stderr
    assert active(owner) == []


def test_a_member_removed_from_the_team_has_their_sessions_ended(team: Team, owner: Session, dana: Session) -> None:
    owner.start()
    dana.start()

    team.owner().call("remove_member", member_id="emp-2")

    assert active(owner) == [("owner-1", "test-session")]


def test_a_member_who_loses_a_restricted_project_has_their_sessions_there_ended(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-sessions", 2211)
    billing = create(signed_out, "Billing")["project_id"]
    checkout = create(signed_out, "Checkout")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev", "dana-sessions")["personal_token"])
    dana.in_project(billing).start()
    dana.in_project(checkout).start()
    owner.in_project(billing).start()

    restricted = signed_out.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})

    assert restricted.status_code == 200, restricted.text
    assert active(owner.in_project(billing)) == [("E1001", "test-session")]
    assert active(owner.in_project(checkout)) == [("emp-2", "test-session")]


def test_a_session_started_through_one_worker_is_active_when_read_through_another(
    owner: Session, second_server: RunningServer
) -> None:
    other = dataclasses.replace(owner, server=second_server)

    owner.start()
    started = active(other)
    other.end()

    assert started == [("owner-1", "test-session")]
    assert active(owner) == []


def test_a_session_idle_by_one_workers_reading_is_idle_by_anothers(
    team: Team, owner: Session, second_server: RunningServer
) -> None:
    other = dataclasses.replace(owner, server=second_server)
    owner.start()

    team.server.clock.advance(minutes=30)

    assert active(owner) == active(other) == []
    assert ENDED in added_context(other.prompt("write a haiku about cats"))


def test_whatever_ends_with_a_session_is_told_when_it_ends_and_when_it_is_back_from_idle(
    team: Team, owner: Session
) -> None:
    """What the modules that keep something per session (its activity, its locks) stand on. `on_gone` is an
    in-process listener with no HTTP surface, so this reads the worker's sessions module and patches nothing."""
    sessions: Sessions = team.server.app.state.sessions
    gone: list[int] = []
    sessions.on_gone(lambda conn, ids: gone.extend(ids))
    owner.start()
    (known,) = owner.active_sessions()

    owner.prompt("write a haiku about cats")
    while_active = list(gone)
    team.server.clock.advance(minutes=30)
    while_idle = sessions.still_active([known.id])
    owner.prompt("write a haiku about cats")
    back = list(gone)
    owner.end()

    assert while_active == []
    assert while_idle == set()
    assert back == [known.id]
    assert gone == [known.id, known.id]
    assert sessions.still_active([known.id]) == set()
