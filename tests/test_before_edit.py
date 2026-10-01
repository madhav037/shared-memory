"""The before-edit hook: a session's edit takes the file's lock, and an edit of a file another session holds is blocked."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

import httpx
import pytest

from tests.support import CLAUDE_EVENTS, REPO_ROOT, WORKING_FOLDER, Session, Team, edit_tool
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
    assert "5 minutes ago" in reason and taken["last_used"] in reason


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
    "copilot-cli": ({"permissionDecision": "deny"}, ()),
    "cursor": ({"permission": "deny"}, ()),
    "cline": ({"cancel": True}, ()),
}
REASON_FIELDS: dict[str | None, tuple[str, ...]] = {
    None: ("permissionDecisionReason",),
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


def test_a_server_error_is_allowed(dana: Session, cole: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    dana.edit(FILE)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(cole.server.app.state.locks, "take", broken)

    assert cole.edit(FILE) == ALLOWED


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


def run_plugin(server_url: str, session: Session, token: str | None) -> subprocess.CompletedProcess[str]:
    """Run the plugin's before-edit command the way Claude Code does: the payload on stdin, the options in the
    environment."""
    assert session.project is not None and session.repository is not None and token is not None
    payload = {
        "session_id": session.identifier,
        "cwd": f"{WORKING_FOLDER}/src",
        "hook_event_name": "PreToolUse",
        **edit_tool(f"{WORKING_FOLDER}/{FILE}"),
    }
    return subprocess.run(
        ["sh", "-c", plugin_command()],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "CLAUDE_PLUGIN_OPTION_SERVER_URL": server_url,
            "CLAUDE_PLUGIN_OPTION_PERSONAL_TOKEN": token,
            "CLAUDE_PROJECT_DIR": WORKING_FOLDER,
            "SHARED_MEMORY_PROJECT": session.project,
            "SHARED_MEMORY_REPOSITORY": session.repository,
        },
    )


needs_a_shell = pytest.mark.skipif(
    shutil.which("sh") is None or shutil.which("curl") is None,
    reason="Claude Code runs the plugin's hooks with curl in a POSIX shell, which aren't both here",
)


@needs_a_shell
def test_claude_codes_plugin_takes_the_lock_and_hands_claude_code_the_block(
    team: Team, dana: Session, cole: Session
) -> None:
    allowed = run_plugin(team.server.url, dana, dana.token)

    blocked = run_plugin(team.server.url, cole, cole.token)

    assert (allowed.returncode, json.loads(allowed.stdout)) == (0, ALLOWED), allowed.stderr
    assert blocked.returncode == 0, blocked.stderr
    assert "Dana Dev (emp-2)" in reason_in(json.loads(blocked.stdout))
    assert "Dana Dev" in refused(cole), "the file is named from the root the plugin sent, not the working folder"


@needs_a_shell
def test_claude_codes_plugin_lets_the_edit_through_with_a_warning_when_the_server_is_down(dana: Session) -> None:
    ran = run_plugin("http://127.0.0.1:9", dana, dana.token)

    said = json.loads(ran.stdout)
    assert ran.returncode == 0, ran.stderr
    assert list(said) == ["systemMessage"]
    assert "Shared Memory" in said["systemMessage"] and "lock" in said["systemMessage"]
