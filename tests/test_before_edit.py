"""The before-edit hook: a session's edit takes the file's lock, and an edit of a file another session holds is blocked."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.connection import BRIEFING_SECONDS, HOOK_SECONDS, connection_kit, repository_root
from shared_memory.embeddings import LazyEmbedder
from tests.support import (
    CLAUDE_EVENTS,
    REPO_ROOT,
    WORKING_FOLDER,
    RunningServer,
    Session,
    Team,
    TestClock,
    edit_tool,
    fresh_database,
    member,
    new_team,
)
from tests.test_locks import FILE, refused, take
from tests.test_sessions import active

ALLOWED: dict[str, Any] = {}


def edit_of(session: Session, file_path: str, tool: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    """The before-edit hook for a file named as the agent names it, in a payload a test shapes itself."""
    payload = {
        "session_id": session.identifier,
        "cwd": WORKING_FOLDER,
        "hook_event_name": CLAUDE_EVENTS["before-edit"],
        **(tool or edit_tool(file_path)),
        **more,
    }
    return session.hook_payload("before-edit", payload)


def reason_in(output: dict[str, Any]) -> str:
    """Why Claude Code is told its edit is blocked."""
    reason: str = output["hookSpecificOutput"]["permissionDecisionReason"]
    return reason


# Allowed, and locked


def test_an_edit_of_a_free_file_is_allowed_and_its_session_then_holds_the_lock(dana: Session, cole: Session) -> None:
    answer = dana.edit(FILE)

    assert answer == ALLOWED
    assert "Dana Dev (emp-2)" in refused(cole), "the file is Dana's session's now"
    assert dana.edit(FILE) == ALLOWED, "its holder goes on editing it"


def test_an_edit_keeps_the_lock_in_use(team: Team, dana: Session, cole: Session) -> None:
    dana.edit(FILE)
    team.server.clock.advance(minutes=10)
    dana.edit(FILE)
    team.server.clock.advance(minutes=2)

    assert "2 minutes ago" in refused(cole)


# Blocked


def test_an_edit_of_a_file_another_session_holds_is_blocked_in_claude_codes_format(
    team: Team, dana: Session, cole: Session
) -> None:
    taken = take(dana.as_agent("claude-code"))
    team.server.clock.advance(minutes=5)

    answer = cole.edit(FILE)

    assert list(answer) == ["hookSpecificOutput"]
    assert answer["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = reason_in(answer)
    assert "Dana Dev (emp-2)" in reason
    assert "Claude Code" in reason
    assert f"billing-api:{FILE}" in reason
    assert "stated no activity" in reason
    assert "5 minutes ago" in reason and taken["last_used_at"] in reason


def test_a_blocked_edit_names_the_holders_activity(dana: Session, cole: Session) -> None:
    dana.call("set_activity", activity="Reworking the webhook retry backoff", session=dana.identifier)
    dana.edit(FILE)

    reason = reason_in(cole.edit(FILE))

    assert "Their activity: Reworking the webhook retry backoff" in reason


def test_a_blocked_edit_says_a_takeover_is_possible_once_the_member_says_so(dana: Session, cole: Session) -> None:
    dana.edit(FILE)

    reason = reason_in(cole.edit(FILE))

    assert "takeover" in reason
    assert "take_lock" in reason
    assert "member" in reason
    assert reason.count("take_lock") == 1, "the takeover advice is stated once"


def hooked_edit(session: Session, agent: str | None = None, format: str | None = None) -> dict[str, Any]:
    """The before-edit hook of a session known only by its hooks, which name their coding agent or their format."""
    answer = httpx.post(
        f"{session.server.url}/hooks/before-edit",
        json={"session_id": session.identifier, "cwd": WORKING_FOLDER, **edit_tool(f"{WORKING_FOLDER}/{FILE}")},
        params={"format": format} if format else None,
        headers={**session.headers(), **({"X-Shared-Memory-Agent": agent} if agent else {})},
        timeout=60,
    )
    said: dict[str, Any] = answer.json()
    return said


@pytest.mark.parametrize(
    ("agent", "format", "named"),
    [
        ("claude-code", None, "in Claude Code,"),
        ("codex", None, "in Codex,"),
        ("devin", None, "in Devin Desktop,"),
        (None, "gemini", "in Gemini CLI,"),
        (None, "copilot-cli", "in GitHub Copilot,"),
        (None, "cursor", "in Cursor,"),
        (None, "cline", "in Cline,"),
        ("nonesuch", "cline", "in Cline,"),
        (None, None, "in a coding agent that has not said which it is,"),
        ("nonesuch", None, "in a coding agent that has not said which it is,"),
    ],
)
def test_a_holder_known_only_by_its_hooks_is_named_with_the_coding_agent_its_hook_came_from(
    dana: Session, cole: Session, agent: str | None, format: str | None, named: str
) -> None:
    assert hooked_edit(dana, agent, format) == ALLOWED

    assert named in reason_in(cole.edit(FILE))
    assert named in refused(cole)


def test_the_coding_agent_a_tool_call_reported_is_not_replaced_by_what_a_hook_says(dana: Session, cole: Session) -> None:
    take(dana.as_agent("codex-mcp-client"))

    hooked_edit(dana, "claude-code")

    assert "in Codex," in refused(cole)


def test_the_coding_agent_a_hook_said_is_replaced_by_what_a_tool_call_reports(dana: Session, cole: Session) -> None:
    hooked_edit(dana, "claude-code")

    take(dana.as_agent("codex-mcp-client"))

    assert "in Codex," in refused(cole)


def test_the_same_members_other_session_is_blocked_too(dana: Session) -> None:
    dana.edit(FILE)

    answer = dana.as_session("second-session").edit(FILE)

    assert "Dana Dev (emp-2)" in reason_in(answer)


def test_a_blocked_edit_leaves_the_lock_with_its_holder(dana: Session, cole: Session) -> None:
    dana.edit(FILE)

    cole.edit(FILE)

    assert dana.edit(FILE) == ALLOWED
    assert "Dana Dev" in reason_in(cole.edit(FILE))


def test_a_file_is_free_to_edit_once_its_holders_session_ends(dana: Session, cole: Session) -> None:
    dana.edit(FILE)
    blocked = cole.edit(FILE)

    dana.end()

    assert blocked != ALLOWED
    assert cole.edit(FILE) == ALLOWED
    assert "Cole Coder" in reason_in(dana.edit(FILE))


# Every family's format

# What an agent of each family reads as "this edit is blocked", and where it reads the reason.
BLOCKED: dict[str | None, tuple[dict[str, Any], tuple[str, ...]]] = {
    None: ({"hookEventName": "PreToolUse", "permissionDecision": "deny"}, ("hookSpecificOutput",)),
    "gemini": ({"decision": "deny"}, ()),
    "devin": ({"decision": "block"}, ()),
    "copilot-cli": ({"permissionDecision": "deny"}, ()),
    "cursor": ({"permission": "deny"}, ()),
    "cline": ({"cancel": True}, ()),
}
REASON_FIELDS: dict[str | None, tuple[str, ...]] = {
    None: ("permissionDecisionReason",),
    "gemini": ("reason",),
    "devin": ("reason",),
    "copilot-cli": ("permissionDecisionReason",),
    "cursor": ("agent_message", "user_message"),  # glossary: Cursor's own field names
    "cline": ("errorMessage",),
}


@pytest.mark.parametrize("format", list(BLOCKED))
def test_every_family_is_answered_blocked_and_allowed_in_its_own_format(
    dana: Session, cole: Session, format: str | None
) -> None:
    allowed = dana.edit(FILE, format=format)

    answer = cole.edit(FILE, format=format)

    says, within = BLOCKED[format]
    for field in within:
        answer = answer[field]
    assert allowed == ALLOWED
    assert says.items() <= answer.items()
    assert sorted(answer) == sorted([*says, *REASON_FIELDS[format]])
    assert all("Dana Dev (emp-2)" in answer[field] for field in REASON_FIELDS[format])


def test_a_format_this_server_does_not_know_is_blocked_as_claude_code_is(dana: Session, cole: Session) -> None:
    dana.edit(FILE)

    answer = cole.edit(FILE, format="nonesuch")

    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert dana.edit(FILE, format="nonesuch") == ALLOWED


# Every agent's own payload

PATCH = """*** Begin Patch
*** Update File: {file}
@@
-retries = 3
+retries = 5
*** End Patch"""


def codex_edit(session: Session, *files: str) -> dict[str, Any]:
    """Codex's PreToolUse payload for apply_patch, whose one argument is the patch."""
    return {
        "session_id": session.identifier,
        "cwd": WORKING_FOLDER,
        "hook_event_name": "PreToolUse",
        "turn_id": "turn-1",
        "tool_name": "apply_patch",
        "tool_use_id": "call_1",
        "tool_input": {"command": "\n".join(PATCH.format(file=file) for file in files)},
    }


#: What each coding agent's own hook sends before a file edit, from that agent's hook reference, the format its kit
#: asks to be answered in, and the header its kit names the repository's root in. None of them was captured from the
#: real agent.
AGENTS_OWN: dict[str, tuple[Callable[[Session, str], dict[str, Any]], str | None, bool]] = {
    "Codex": (codex_edit, None, False),
    "Gemini CLI": (
        lambda session, file: {
            "session_id": session.identifier,
            "cwd": f"{WORKING_FOLDER}/src",
            "hook_event_name": "BeforeTool",
            "timestamp": "2026-10-02T09:00:00Z",
            "tool_name": "replace",
            "tool_input": {"file_path": f"{WORKING_FOLDER}/{file}", "old_string": "3", "new_string": "5"},
        },
        "gemini",
        True,
    ),
    "Devin Desktop": (
        lambda session, file: {
            "hook_event_name": "PreToolUse",
            "session_id": session.identifier,
            "prompt_id": "prompt-1",
            "tool_name": "edit",
            "tool_input": {"file_path": f"{WORKING_FOLDER}/{file}", "old_string": "3", "new_string": "5"},
        },
        "devin",
        True,
    ),
    "Copilot CLI": (
        lambda session, file: {
            "sessionId": session.identifier,
            "timestamp": 1790931600000,
            "cwd": WORKING_FOLDER,
            "toolName": "edit",
            "toolArgs": json.dumps({"path": f"{WORKING_FOLDER}/{file}", "old_str": "3", "new_str": "5"}),
        },
        "copilot-cli",
        False,
    ),
    "Cursor": (
        lambda session, file: {
            "conversation_id": session.identifier,
            "generation_id": "generation-1",
            "hook_event_name": "preToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": f"{WORKING_FOLDER}/{file}", "old_string": "3", "new_string": "5"},
            "tool_use_id": "tool-1",
            "workspace_roots": [WORKING_FOLDER],
        },
        "cursor",
        False,
    ),
    "Cline": (
        lambda session, file: {
            "taskId": session.identifier,
            "hookName": "PreToolUse",
            "clineVersion": "3.36.0",
            "timestamp": "1790931600000",
            "workspaceRoots": [WORKING_FOLDER],
            "preToolUse": {"tool": "write_to_file", "parameters": {"path": file, "content": "retries = 5"}},
        },
        "cline",
        False,
    ),
}


def own_edit(session: Session, agent: str, file: str = FILE, root: str | None = None) -> dict[str, Any]:
    """Fire the before-edit hook as this coding agent's kit does: its own payload, format and headers, or the root
    given here in place of the one its kit names."""
    payload, format, names_root = AGENTS_OWN[agent]
    root = root or (WORKING_FOLDER if names_root else None)
    answer = httpx.post(
        f"{session.server.url}/hooks/before-edit",
        json=payload(session, file),
        params={"format": format} if format else None,
        headers={**session.headers(), **({"X-Shared-Memory-Root": root} if root else {})},
        timeout=60,
    )
    assert answer.status_code == 200, answer.text
    said: dict[str, Any] = answer.json()
    return said


@pytest.mark.parametrize("agent", list(AGENTS_OWN))
def test_every_agents_own_before_edit_payload_takes_a_free_file_and_is_blocked_on_a_held_one(
    dana: Session, cole: Session, agent: str
) -> None:
    allowed = own_edit(dana, agent)

    answer = own_edit(cole, agent)

    says, within = BLOCKED[AGENTS_OWN[agent][1]]
    for field in within:
        answer = answer[field]
    assert allowed == ALLOWED
    assert "Dana Dev (emp-2)" in refused(cole), "the file is locked by its path from the repository's root"
    assert says.items() <= answer.items()
    assert all("Dana Dev (emp-2)" in answer[field] for field in REASON_FIELDS[AGENTS_OWN[agent][1]])
    assert own_edit(dana, agent) == ALLOWED, "its holder goes on editing it"


def test_a_codex_patch_of_several_files_takes_each_lock_and_is_blocked_when_one_is_held(
    dana: Session, cole: Session
) -> None:
    assert dana.hook_payload("before-edit", codex_edit(dana, FILE, "docs/retries.md")) == ALLOWED

    answer = cole.hook_payload("before-edit", codex_edit(cole, "README.md", "docs/retries.md"))

    assert "Dana Dev" in refused(cole) and "Dana Dev" in refused(cole, "docs/retries.md")
    assert "billing-api:docs/retries.md" in reason_in(answer)


def test_a_blocked_patch_of_several_files_leaves_its_session_holding_none_it_took_for_it(
    team: Team, dana: Session, cole: Session, owner: Session
) -> None:
    """Nothing was edited, so the files named before the held one stay free; what the session held already stays its."""
    dana.edit("docs/retries.md")
    cole.edit("CHANGELOG.md")
    team.server.clock.advance(minutes=1)

    answer = cole.hook_payload("before-edit", codex_edit(cole, "CHANGELOG.md", "README.md", "docs/retries.md", FILE))

    assert "billing-api:docs/retries.md" in reason_in(answer)
    assert "Cole Coder" in refused(owner, "CHANGELOG.md"), "held before the blocked edit, and still"
    assert take(owner, "README.md")["locked"] is True, "taken for the blocked edit, and given up with it"
    assert take(owner, FILE)["locked"] is True, "never reached"
    assert cole.hook_payload("before-edit", codex_edit(cole, "CHANGELOG.md", "src/free.py")) == ALLOWED
    assert "Cole Coder" in refused(owner, "src/free.py"), "a patch that is allowed keeps every lock it took"


def test_a_tool_that_only_reads_a_file_takes_no_lock(dana: Session, cole: Session) -> None:
    viewed = {
        "sessionId": dana.identifier,
        "cwd": WORKING_FOLDER,
        "toolName": "view",
        "toolArgs": {"path": f"{WORKING_FOLDER}/{FILE}"},
    }
    read = {
        "taskId": dana.identifier,
        "hookName": "PreToolUse",
        "workspaceRoots": [WORKING_FOLDER],
        "preToolUse": {"tool": "read_file", "parameters": {"path": FILE}},
    }

    assert dana.hook_payload("before-edit", viewed, "copilot-cli") == ALLOWED
    assert dana.hook_payload("before-edit", read, "cline") == ALLOWED

    assert take(cole)["locked"] is True, "nobody holds a file that was only read"


def test_cursors_session_is_the_one_its_edits_name_when_its_end_names_two(dana: Session, cole: Session) -> None:
    """Cursor's session end sends a session_id beside the conversation_id that every one of its payloads carries."""
    own_edit(dana, "Cursor")

    dana.hook_payload(
        "session-end",
        {"conversation_id": dana.identifier, "session_id": "another-name", "reason": "user_close"},
        "cursor",
    )

    assert own_edit(cole, "Cursor") == ALLOWED


# The hooks the connection kit hands each agent, run as the agent runs them


def kit(session: Session, server_url: str | None = None) -> dict[str, str]:
    """The connection kit's files for this session's repository, by path, pointed at this server or another."""
    assert session.project is not None and session.repository is not None
    files = connection_kit(
        server_url=server_url or session.server.url,
        marketplace="madhav037/shared-memory",
        project_id=session.project,
        project_name="Billing",
        repository=session.repository,
    )
    return {file["path"]: file["contents"] for file in files}


#: Where each agent's kit keeps the command its before-edit hook runs in a POSIX shell. Cline's is a whole script.
KIT_COMMANDS: dict[str, Callable[[dict[str, str]], str]] = {
    "Codex": lambda files: tomllib.loads(files[".codex/config.toml"])["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
    "Cursor": lambda files: json.loads(files[".cursor/hooks.json"])["hooks"]["preToolUse"][0]["command"],
    "Devin Desktop": lambda files: json.loads(files[".devin/hooks.v1.json"])["PreToolUse"][0]["hooks"][0]["command"],
    "Cline": lambda files: files[".clinerules/hooks/PreToolUse"],
}


def run_kit(argv: list[str], session: Session, agent: str) -> subprocess.CompletedProcess[str]:
    """Run a kit's before-edit hook the way its agent does: the agent's own payload on stdin, the member's personal
    token and the agent's own word for the repository's root in the environment."""
    assert session.token is not None
    return subprocess.run(
        argv,
        input=json.dumps(AGENTS_OWN[agent][0](session, FILE)),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "SHARED_MEMORY_TOKEN": session.token,
            "DEVIN_PROJECT_DIR": WORKING_FOLDER,
            "GEMINI_PROJECT_DIR": WORKING_FOLDER,
        },
    )


needs_a_shell = pytest.mark.skipif(
    shutil.which("sh") is None or shutil.which("curl") is None,
    reason="these hooks run curl in a POSIX shell, which aren't both here",
)


@needs_a_shell
@pytest.mark.parametrize("agent", list(KIT_COMMANDS))
def test_a_kits_before_edit_command_takes_the_lock_and_hands_its_agent_the_block(
    dana: Session, cole: Session, agent: str
) -> None:
    command = KIT_COMMANDS[agent](kit(dana))

    allowed = run_kit(["sh", "-c", command], dana, agent)
    blocked = run_kit(["sh", "-c", command], cole, agent)

    says, within = BLOCKED[AGENTS_OWN[agent][1]]
    answer = json.loads(blocked.stdout)
    for field in within:
        answer = answer[field]
    assert (allowed.returncode, json.loads(allowed.stdout)) == (0, ALLOWED), allowed.stderr
    assert blocked.returncode == 0, blocked.stderr
    assert says.items() <= answer.items()
    assert "Dana Dev" in refused(cole), "the file is locked by its path from the repository's root"
    assert f"in {agent}," in refused(cole), "the kit's hook says which coding agent it runs in"


@needs_a_shell
@pytest.mark.parametrize("agent", list(KIT_COMMANDS))
def test_a_kits_before_edit_command_lets_the_edit_through_when_the_server_is_down(dana: Session, agent: str) -> None:
    command = KIT_COMMANDS[agent](kit(dana, "http://127.0.0.1:9"))

    ran = run_kit(["sh", "-c", command], dana, agent)

    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() in ("", "{}"), "nothing that blocks the edit"
    assert "--max-time 3 " in command


@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_geminis_hook_script_takes_the_lock_and_hands_gemini_the_block(
    dana: Session, cole: Session, tmp_path: Path
) -> None:
    script = tmp_path / "shared-memory.mjs"
    script.write_text(kit(dana)[".gemini/hooks/shared-memory.mjs"], encoding="utf-8")

    allowed = run_kit(["node", str(script), "before-edit"], dana, "Gemini CLI")
    blocked = run_kit(["node", str(script), "before-edit"], cole, "Gemini CLI")

    assert (allowed.returncode, json.loads(allowed.stdout)) == (0, ALLOWED), allowed.stderr
    assert json.loads(blocked.stdout)["decision"] == "deny"
    assert "Dana Dev (emp-2)" in json.loads(blocked.stdout)["reason"]
    assert "Dana Dev" in refused(cole)


# Everything else lets the edit through


def test_a_file_that_never_locks_is_allowed_for_every_session(dana: Session, cole: Session) -> None:
    assert dana.edit("uv.lock") == ALLOWED
    assert cole.edit("uv.lock") == ALLOWED
    assert dana.edit("console/dist/assets/index.js") == ALLOWED
    assert cole.edit("console/package-lock.json") == ALLOWED


def test_a_file_outside_the_repository_is_allowed_for_every_session(dana: Session, cole: Session) -> None:
    for outside in ("/home/dana/.claude/plans/next.md", "/work/application/main.py", f"{WORKING_FOLDER}/../other/a.py"):
        assert edit_of(dana, outside) == ALLOWED, outside
        assert edit_of(cole, outside) == ALLOWED, outside


def test_a_payload_the_server_cannot_read_is_allowed(dana: Session, cole: Session) -> None:
    dana.edit(FILE)
    unreadable = httpx.post(f"{cole.server.url}/hooks/before-edit", content=b"not json", headers=cole.headers())

    assert (unreadable.status_code, unreadable.json()) == (200, ALLOWED)
    assert cole.hook_payload("before-edit", {"hook_event_name": "PreToolUse"}) == ALLOWED, "no session, no file"
    assert edit_of(cole, FILE, tool={"tool_name": "Edit"}) == ALLOWED, "no tool input"
    assert edit_of(cole, FILE, tool={"tool_name": "Edit", "tool_input": {"file_path": 7}}) == ALLOWED
    assert edit_of(cole, f"{WORKING_FOLDER}/{FILE}", session_id=None) == ALLOWED, "a payload naming no session"
    assert edit_of(cole, f"{WORKING_FOLDER}/{FILE}", cwd=None) == ALLOWED, "a payload naming no working folder"


def test_an_unknown_personal_token_is_allowed(team: Team, dana: Session) -> None:
    dana.edit(FILE)
    unknown = Session(team.server, "smt_nope", dana.project, "billing-api")

    for format in BLOCKED:
        assert unknown.edit(FILE, format=format) == ALLOWED, format
    assert team.owner().edit(FILE) == ALLOWED, "a session outside any project"


def test_a_session_whose_connection_names_no_repository_is_allowed(team: Team, dana: Session) -> None:
    dana.edit(FILE)
    nowhere = Session(team.server, dana.token, dana.project, None, identifier="no-repository")

    assert nowhere.edit(FILE) == ALLOWED


def test_a_server_error_is_allowed(tmp_path_factory: pytest.TempPathFactory) -> None:
    """On a server of its own, whose locks table is dropped under it, so every lock it reads or takes fails."""
    settings = Settings(
        database_url=fresh_database("shared_memory_broken_locks"),
        memory_root=tmp_path_factory.mktemp("broken-locks-memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
    )
    clock = TestClock()
    with start_blocking_portal() as portal:
        server = RunningServer(
            build_app(settings, clock=clock, embedder=LazyEmbedder(settings.model_cache)), settings, clock, portal
        )
        try:
            team = new_team(server)
            project: str = team.owner().call("create_project", name="Billing")["project_id"]
            dana = member(team, project, "emp-2", "Dana Dev")
            cole = member(team, project, "emp-3", "Cole Coder")
            dana.edit(FILE)
            with psycopg.connect(settings.database_url, autocommit=True) as conn:
                conn.execute("DROP TABLE locks CASCADE")

            assert cole.edit(FILE) == ALLOWED
        finally:
            server.stop()


# The session


def test_an_edit_keeps_its_session_active(team: Team, dana: Session) -> None:
    dana.start()
    team.server.clock.advance(minutes=20)

    dana.edit(FILE)
    team.server.clock.advance(minutes=20)

    assert active(dana) == [("emp-2", "test-session")]


def test_a_blocked_edit_and_an_edit_of_a_file_that_never_locks_keep_their_sessions_active(
    team: Team, dana: Session, cole: Session
) -> None:
    dana.start()
    cole.start()
    team.server.clock.advance(minutes=20)

    dana.edit(FILE)
    cole.edit(FILE)
    team.server.clock.advance(minutes=20)
    cole.edit("uv.lock")
    team.server.clock.advance(minutes=20)

    assert active(cole) == [("emp-3", "test-session")]


# The file, from the repository's root


def test_claude_codes_other_file_edit_tools_name_their_file_too(dana: Session, cole: Session) -> None:
    written = {"tool_name": "Write", "tool_input": {"file_path": f"{WORKING_FOLDER}/docs/new.md", "content": "# New"}}
    notebook = {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": f"{WORKING_FOLDER}/analysis/churn.ipynb", "new_source": "df.head()"},
    }

    assert edit_of(dana, "", tool=written) == ALLOWED
    assert edit_of(dana, "", tool=notebook) == ALLOWED

    assert "Dana Dev" in refused(cole, "docs/new.md")
    assert "Dana Dev" in refused(cole, "analysis/churn.ipynb")


def test_a_windows_path_is_read_from_the_repositorys_root_whatever_its_case_and_slashes(
    dana: Session, cole: Session
) -> None:
    answer = edit_of(dana, r"e:\Codes\Billing-API\src\webhooks\retry.py", cwd=r"E:\Codes\billing-api")

    assert answer == ALLOWED
    assert "Dana Dev" in refused(cole), FILE
    assert "Dana Dev" in reason_in(edit_of(cole, "E:/Codes/billing-api/src/webhooks/retry.py", cwd="E:/Codes/billing-api/"))
    assert edit_of(cole, r"E:\Codes\billing-web\src\webhooks\retry.py", cwd=r"E:\Codes\billing-api") == ALLOWED


def test_a_path_already_written_from_the_root_is_taken_as_it_is(dana: Session, cole: Session) -> None:
    assert edit_of(dana, "src\\webhooks\\retry.py") == ALLOWED

    assert "Dana Dev" in refused(cole)


def test_the_root_the_hook_names_is_used_rather_than_a_working_folder_inside_it(dana: Session, cole: Session) -> None:
    """Claude Code's working folder moves when its shell does; where it was started doesn't."""
    payload = {
        "session_id": dana.identifier,
        "cwd": f"{WORKING_FOLDER}/console",
        "hook_event_name": "PreToolUse",
        **edit_tool(f"{WORKING_FOLDER}/console/src/App.tsx"),
    }
    answer = httpx.post(
        f"{dana.server.url}/hooks/before-edit",
        json=payload,
        headers={**dana.headers(), "X-Shared-Memory-Root": WORKING_FOLDER},
    )

    assert answer.json() == ALLOWED
    assert "Dana Dev" in refused(cole, "console/src/App.tsx")


# Claude Code's plugin


def plugin_entry() -> dict[str, Any]:
    hooks = json.loads((REPO_ROOT / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (entry,) = hooks["PreToolUse"]
    assert isinstance(entry, dict)
    return entry


def plugin_command() -> str:
    (hook,) = plugin_entry()["hooks"]
    assert hook["type"] == "command"
    command: str = hook["command"]
    return command


def test_claude_codes_plugin_runs_the_hook_before_its_file_edit_tools_and_gives_up_at_three_seconds() -> None:
    entry = plugin_entry()
    (hook,) = entry["hooks"]
    command = plugin_command()
    _, fallback = command.split(" || ")

    assert entry["matcher"].split("|") == ["Edit", "Write", "MultiEdit", "NotebookEdit"]
    assert '"$CLAUDE_PLUGIN_OPTION_SERVER_URL/hooks/before-edit"' in command
    assert "--max-time 3 " in command
    assert hook["timeout"] == 4, "Claude Code lets curl give up first, so its fallback runs"
    assert fallback.startswith("echo '") and fallback.endswith("'")
    said = json.loads(fallback[len("echo '") : -1])
    assert list(said) == ["systemMessage"], "a warning for the member, and nothing that blocks the edit"


def test_claude_codes_plugin_waits_as_long_as_every_other_agents_hooks() -> None:
    hooks = json.loads((REPO_ROOT / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    for event, entries in hooks.items():
        seconds = BRIEFING_SECONDS if event == "SessionStart" else HOOK_SECONDS
        for entry in entries:
            for hook in entry["hooks"]:
                assert f"--max-time {seconds} " in hook["command"], event
                assert hook["timeout"] == seconds + 1, event


def run_plugin(
    server_url: str,
    session: Session,
    token: str | None,
    started_in: str | None = WORKING_FOLDER,
    file: str = f"{WORKING_FOLDER}/{FILE}",
) -> subprocess.CompletedProcess[str]:
    """Run the plugin's before-edit command the way Claude Code does: the payload on stdin, the options in the
    environment, and the folder Claude Code was started in as CLAUDE_PROJECT_DIR."""
    assert session.project is not None and session.repository is not None and token is not None
    payload = {
        "session_id": session.identifier,
        "cwd": f"{WORKING_FOLDER}/src",
        "hook_event_name": "PreToolUse",
        **edit_tool(file),
    }
    environment = {
        **os.environ,
        "CLAUDE_PLUGIN_OPTION_SERVER_URL": server_url,
        "CLAUDE_PLUGIN_OPTION_PERSONAL_TOKEN": token,
        "SHARED_MEMORY_PROJECT": session.project,
        "SHARED_MEMORY_REPOSITORY": session.repository,
    }
    environment.pop("CLAUDE_PROJECT_DIR", None)
    if started_in is not None:
        environment["CLAUDE_PROJECT_DIR"] = started_in
    return subprocess.run(
        ["sh", "-c", plugin_command()], input=json.dumps(payload), capture_output=True, text=True, timeout=60,
        env=environment,
    )  # fmt: skip


# A session started in a subfolder of its repository (#241)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="the hooks ask git where the repository's root is")


@pytest.fixture
def subfolder(tmp_path: Path) -> Path:
    """The folder a coding agent was started in: `console`, inside a real git repository."""
    repository = tmp_path / "billing-api"
    (repository / "console" / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True, capture_output=True)
    return repository / "console"


def test_claude_codes_plugin_asks_git_for_the_repositorys_root_within_the_same_command() -> None:
    command = plugin_command()

    assert f'-H "X-Shared-Memory-Root: {repository_root("CLAUDE_PROJECT_DIR")}"' in command
    assert 'git -C "$CLAUDE_PROJECT_DIR" rev-parse --show-cdup 2>/dev/null' in command
    assert command.count(" || ") == 1, "git failing is not what makes the command fall back to its warning"


@needs_a_shell
@needs_git
def test_claude_code_started_in_a_subfolder_names_its_locks_from_the_repositorys_root(
    team: Team, dana: Session, cole: Session, subfolder: Path
) -> None:
    inside = run_plugin(team.server.url, dana, dana.token, str(subfolder), str(subfolder / "src" / "App.tsx"))
    above = run_plugin(team.server.url, dana, dana.token, str(subfolder), str(subfolder.parent / "README.md"))

    assert json.loads(inside.stdout) == ALLOWED, inside.stderr
    assert json.loads(above.stdout) == ALLOWED, above.stderr
    assert "Dana Dev" in refused(cole, "console/src/App.tsx"), "as a session started at the root names it"
    assert "Dana Dev" in refused(cole, "README.md"), "a file above the subfolder is inside the repository"
    assert take(cole, "src/App.tsx")["locked"] is True, "and under no second name"


@needs_a_shell
def test_claude_code_started_outside_a_repository_names_its_locks_from_where_it_was_started(
    team: Team, dana: Session, cole: Session, tmp_path: Path
) -> None:
    ran = run_plugin(team.server.url, dana, dana.token, str(tmp_path), str(tmp_path / "src" / "App.tsx"))

    assert json.loads(ran.stdout) == ALLOWED, ran.stderr
    assert "Dana Dev" in refused(cole, "src/App.tsx")


@needs_a_shell
def test_a_plugin_hook_given_no_folder_leaves_the_root_to_the_payloads_working_folder(
    team: Team, dana: Session, cole: Session
) -> None:
    ran = run_plugin(team.server.url, dana, dana.token, started_in=None)

    assert json.loads(ran.stdout) == ALLOWED, ran.stderr
    assert "Dana Dev" in refused(cole, "webhooks/retry.py"), "from the payload's cwd, /work/app/src"


def run_kit_started_in(argv: list[str], session: Session, agent: str, started_in: Path) -> None:
    """Run a kit's before-edit hook for an edit of src/App.tsx by an agent started in this folder."""
    assert session.token is not None
    payload = AGENTS_OWN[agent][0](session, FILE)
    payload["tool_input"]["file_path"] = str(started_in / "src" / "App.tsx")
    payload.update({"cwd": str(started_in)} if "cwd" in payload else {})
    ran = subprocess.run(
        argv,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "SHARED_MEMORY_TOKEN": session.token,
            "DEVIN_PROJECT_DIR": str(started_in),
            "GEMINI_PROJECT_DIR": str(started_in),
        },
    )
    assert (ran.returncode, json.loads(ran.stdout)) == (0, ALLOWED), ran.stderr


@needs_a_shell
@needs_git
def test_devin_started_in_a_subfolder_names_its_locks_from_the_repositorys_root(
    dana: Session, cole: Session, subfolder: Path
) -> None:
    command = KIT_COMMANDS["Devin Desktop"](kit(dana))

    run_kit_started_in(["sh", "-c", command], dana, "Devin Desktop", subfolder)

    assert "Dana Dev" in refused(cole, "console/src/App.tsx")


@needs_git
@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_gemini_started_in_a_subfolder_names_its_locks_from_the_repositorys_root(
    dana: Session, cole: Session, subfolder: Path, tmp_path: Path
) -> None:
    script = tmp_path / "shared-memory.mjs"
    script.write_text(kit(dana)[".gemini/hooks/shared-memory.mjs"], encoding="utf-8")

    run_kit_started_in(["node", str(script), "before-edit"], dana, "Gemini CLI", subfolder)

    assert "Dana Dev" in refused(cole, "console/src/App.tsx")


# Codex, Cursor and Cline name no folder to their hooks, so their kits ask git from where the command runs (#249)

#: The agents whose kit names the root from the folder its hook's command runs in.
RUN_IN_A_FOLDER = ("Codex", "Cursor", "Cline")


@pytest.mark.parametrize("agent", (*RUN_IN_A_FOLDER, "Copilot CLI"))
def test_a_root_that_does_not_hold_the_edited_file_gives_way_to_the_payloads_folders(
    dana: Session, cole: Session, agent: str
) -> None:
    """A hook run somewhere other than the session's folder names the wrong root; the edit still takes its lock."""
    assert own_edit(dana, agent, root="/home/dana/other-repository") == ALLOWED

    assert "Dana Dev" in refused(cole), "named from the payload's folder, as before any hook named a root"


def test_a_relative_path_is_read_from_the_payloads_working_folder_below_the_root(dana: Session, cole: Session) -> None:
    """Codex's patch and Cline's tools name a file from the folder the session works in, which may be a subfolder."""
    payload = codex_edit(dana, "src/App.tsx")
    payload["cwd"] = f"{WORKING_FOLDER}/console"
    answer = httpx.post(
        f"{dana.server.url}/hooks/before-edit",
        json=payload,
        headers={**dana.headers(), "X-Shared-Memory-Root": f"{WORKING_FOLDER}/console/../"},
    )

    assert answer.json() == ALLOWED
    assert "Dana Dev" in refused(cole, "console/src/App.tsx")
    assert take(cole, "src/App.tsx")["locked"] is True, "and under no second name"


def as_the_shell_names_it(folder: Path) -> str:
    """The folder as a POSIX shell's $PWD names it there, which is how an agent on macOS or Linux names its files.
    Git Bash on Windows writes /c/... where Python writes C:\\..."""
    return subprocess.run(["sh", "-c", "pwd"], cwd=folder, capture_output=True, text=True, check=True).stdout.strip()


def run_kit_in(argv: list[str], session: Session, agent: str, runs_in: Path, works_in: str) -> None:
    """Run a kit's before-edit hook in one folder for an edit of src/App.tsx by a session working in another, with the
    agent's own payload naming that folder and the file as its agent does."""
    assert session.token is not None
    written = json.dumps(AGENTS_OWN[agent][0](session, "src/App.tsx"))
    payload = written.replace(json.dumps(WORKING_FOLDER)[1:-1], json.dumps(works_in)[1:-1])
    ran = subprocess.run(
        argv,
        input=payload,
        cwd=runs_in,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "SHARED_MEMORY_TOKEN": session.token},
    )
    assert (ran.returncode, json.loads(ran.stdout)) == (0, ALLOWED), ran.stderr


@needs_a_shell
@needs_git
@pytest.mark.parametrize("agent", RUN_IN_A_FOLDER)
def test_codex_cursor_and_cline_started_in_a_subfolder_name_their_locks_from_the_repositorys_root(
    dana: Session, cole: Session, subfolder: Path, agent: str
) -> None:
    command = KIT_COMMANDS[agent](kit(dana))

    run_kit_in(["sh", "-c", command], dana, agent, subfolder, as_the_shell_names_it(subfolder))

    assert "Dana Dev" in refused(cole, "console/src/App.tsx"), "as a session started at the root names it"
    assert take(cole, "src/App.tsx")["locked"] is True, "and under no second name"


@needs_a_shell
@needs_git
@pytest.mark.parametrize("agent", RUN_IN_A_FOLDER)
def test_a_kits_command_run_in_another_repository_leaves_the_root_to_the_payload(
    dana: Session, cole: Session, subfolder: Path, tmp_path: Path, agent: str
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    subprocess.run(["git", "init", "--quiet", str(elsewhere)], check=True, capture_output=True)
    command = KIT_COMMANDS[agent](kit(dana))

    run_kit_in(["sh", "-c", command], dana, agent, elsewhere, as_the_shell_names_it(subfolder))

    assert "Dana Dev" in refused(cole, "src/App.tsx"), "locked from the payload's folder, as before, not let through"


@needs_a_shell
@pytest.mark.parametrize("agent", RUN_IN_A_FOLDER)
def test_a_kits_command_run_outside_a_repository_leaves_the_root_to_the_payload(
    dana: Session, cole: Session, tmp_path: Path, agent: str
) -> None:
    (tmp_path / "src").mkdir()
    command = KIT_COMMANDS[agent](kit(dana))

    run_kit_in(["sh", "-c", command], dana, agent, tmp_path, as_the_shell_names_it(tmp_path))

    assert "Dana Dev" in refused(cole, "src/App.tsx")


@needs_git
@pytest.mark.skipif(shutil.which("pwsh") is None, reason="Cline runs its Windows hooks in PowerShell, which isn't here")
def test_clines_windows_script_started_in_a_subfolder_names_its_locks_from_the_repositorys_root(
    dana: Session, cole: Session, subfolder: Path, tmp_path: Path
) -> None:
    script = tmp_path / "PreToolUse.ps1"
    script.write_text(kit(dana)[".clinerules/hooks/PreToolUse.ps1"], encoding="utf-8")

    run_kit_in(["pwsh", "-NoProfile", "-File", str(script)], dana, "Cline", subfolder, str(subfolder))

    assert "Dana Dev" in refused(cole, "console/src/App.tsx")


@needs_a_shell
def test_claude_codes_plugin_takes_the_lock_and_hands_claude_code_the_block(
    team: Team, dana: Session, cole: Session
) -> None:
    allowed = run_plugin(team.server.url, dana, dana.token)

    blocked = run_plugin(team.server.url, cole, cole.token)

    assert (allowed.returncode, json.loads(allowed.stdout)) == (0, ALLOWED), allowed.stderr
    assert blocked.returncode == 0, blocked.stderr
    assert "Dana Dev (emp-2)" in reason_in(json.loads(blocked.stdout))
    assert "in Claude Code," in reason_in(json.loads(blocked.stdout)), "the plugin's hooks say they are Claude Code's"
    assert "Dana Dev" in refused(cole), "the file is named from the root the plugin sent, not the working folder"


@needs_a_shell
def test_claude_codes_plugin_lets_the_edit_through_with_a_warning_when_the_server_is_down(dana: Session) -> None:
    ran = run_plugin("http://127.0.0.1:9", dana, dana.token)

    said = json.loads(ran.stdout)
    assert ran.returncode == 0, ran.stderr
    assert list(said) == ["systemMessage"]
    assert "Shared Memory" in said["systemMessage"] and "lock" in said["systemMessage"]
