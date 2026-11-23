"""Connecting a repository: the files each coding agent commits so its sessions reach the project."""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import threading
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from shared_memory.agents import agent_named
from shared_memory.config import STAND_BY_TOOL_CAP_SECONDS, Settings
from shared_memory.connection import (
    STAND_BY_WITH_THE_TOOL,
    STANDBY_COMMAND_SECONDS,
    connection_kit,
    guidance_name,
    repository_branch,
    repository_root,
    stands_by,
    working_folder_branch,
)
from shared_memory.hooks import AGENTS, CLAUDE_CODE, GEMINI_CLI
from shared_memory.standby import STAND_BY_SECONDS
from tests.support import REPO_ROOT, Session, Company, edit_tool, member


def by_path(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {file["path"]: file for file in files}


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.name)
def test_the_name_each_agents_hooks_send_is_known_as_that_agent(agent: Any) -> None:
    assert agent_named(agent.header) == agent.name


def test_connecting_a_repository_gives_each_agent_the_files_it_commits(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]
    files = by_path(created["files"])

    claude = json.loads(files[".claude/settings.json"]["contents"])
    codex = tomllib.loads(files[".codex/config.toml"]["contents"])["mcp_servers"]["shared-memory"]

    assert files[".claude/settings.json"]["agent"] == "Claude Code"
    assert claude["env"] == {"SHARED_MEMORY_PROJECT": project, "SHARED_MEMORY_REPOSITORY": "billing-api"}
    assert files[".codex/config.toml"]["agent"] == "Codex"
    assert codex["url"] == f"{company.server.url}/mcp"
    assert codex["bearer_token_env_var"] == "SHARED_MEMORY_TOKEN"
    assert codex["http_headers"] == {"X-Shared-Memory-Project": project, "X-Shared-Memory-Repository": "billing-api"}


def test_every_agent_is_told_in_agents_md_how_to_use_the_projects_memory(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")

    section = by_path(created["files"])["AGENTS.md"]

    assert section["agent"] == "Every agent"
    assert section["action"] == "merge"
    for needed in (created["project_id"], "billing-api", "briefing", "search", "remember", "SHARED_MEMORY_TOKEN"):
        assert needed in section["contents"], needed


#: The plugin's copy is the source. The package's is the one the server serves, because the Dockerfile copies
#: `src/` and nothing else, and Claude Code loads a plugin skill only from `plugin/skills/<name>/SKILL.md`.
SYNC = (
    "The skill has drifted. The plugin's copy is the source; copy it over the package's:\n"
    "  cp plugin/skills/shared-memory/SKILL.md src/shared_memory/skill.md"
)


def test_the_skill_every_agent_reads_is_the_one_claude_code_ships(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")

    skill = by_path(created["files"])[".agents/skills/shared-memory/SKILL.md"]

    shipped = (REPO_ROOT / "plugin" / "skills" / "shared-memory" / "SKILL.md").read_text(encoding="utf-8")
    assert skill["contents"] == shipped, SYNC
    assert skill["action"] == "create"


def test_no_connection_file_carries_a_personal_token(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")

    for file in created["files"]:
        assert company.owner_token not in file["contents"], file["path"]
        assert "smt_" not in file["contents"], file["path"]


def mcp_server(file: dict[str, Any], section: str = "mcpServers", name: str = "shared-memory") -> dict[str, Any]:
    server: dict[str, Any] = json.loads(file["contents"])[section][name]
    return server


def test_every_agent_with_a_repository_file_is_pointed_at_the_project(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]
    files = by_path(created["files"])
    expected = {"X-Shared-Memory-Project": project, "X-Shared-Memory-Repository": "billing-api"}

    vscode = mcp_server(files[".vscode/mcp.json"], section="servers")
    copilot_cli = mcp_server(files[".github/mcp.json"])
    gemini = json.loads(files[".gemini/settings.json"]["contents"])
    cursor = mcp_server(files[".cursor/mcp.json"])
    devin = mcp_server(files[".devin/mcp_config.json"])

    for server in (vscode, copilot_cli, gemini["mcpServers"]["shared-memory"], cursor, devin):
        assert server["url"] == f"{company.server.url}/mcp"
        assert {name: value for name, value in server["headers"].items() if name != "Authorization"} == expected
    assert vscode["headers"]["Authorization"] == "Bearer ${input:shared-memory-token}"
    assert copilot_cli["headers"]["Authorization"] == "Bearer ${SHARED_MEMORY_TOKEN}"
    assert gemini["mcpServers"]["shared-memory"]["headers"]["Authorization"] == "Bearer ${SHARED_MEMORY_TOKEN}"
    assert cursor["headers"]["Authorization"] == "Bearer ${env:SHARED_MEMORY_TOKEN}"
    assert devin["headers"]["Authorization"] == "Bearer ${env:SHARED_MEMORY_TOKEN}"
    assert "AGENTS.md" in gemini["context"]["fileName"]
    assert {files[path]["agent"] for path in files} >= {
        "GitHub Copilot", "Gemini CLI", "Cursor", "Devin Desktop", "Cline"
    }


def test_cline_is_set_up_once_per_project_on_each_members_machine_for_every_repository(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]

    cline = next(file for file in created["files"] if file["agent"] == "Cline")
    server = mcp_server(cline, name=f"shared-memory-{project}")

    assert cline["kept_in"] == "machine"
    assert server["type"] == "streamableHttp"
    assert server["headers"] == {"Authorization": "Bearer ${env:SHARED_MEMORY_TOKEN}", "X-Shared-Memory-Project": project}
    assert all(file["kept_in"] == "repository" for file in created["files"] if file["agent"] != "Cline")


def test_codex_is_briefed_and_recalls_through_the_shell_of_whichever_machine_it_runs_on(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    hooks = tomllib.loads(by_path(created["files"])[".codex/config.toml"]["contents"])["hooks"]

    briefing = hooks["SessionStart"][0]["hooks"][0]
    recall = hooks["UserPromptSubmit"][0]["hooks"][0]
    before_edit = hooks["PreToolUse"][0]["hooks"][0]
    end = hooks["SessionEnd"][0]["hooks"][0]

    assert "matcher" not in hooks["PreToolUse"][0], "the hook before a tool runs on every tool (ADR-0025)"
    assert "compact" in hooks["SessionStart"][0]["matcher"], "a compaction starts the session's recall over"
    assert end["timeout"] <= 3, "Codex gives a SessionEnd hook 3 seconds at most"
    for hook, event in (
        (briefing, "session-start"),
        (recall, "prompt-submitted"),
        (before_edit, "before-edit"),
        (end, "session-end"),
    ):
        assert hook["type"] == "command"
        assert f"{company.server.url}/hooks/{event}" in hook["command"], event
        assert "$SHARED_MEMORY_TOKEN" in hook["command"], event
        assert f"{company.server.url}/hooks/{event}" in hook["command_windows"], event
        assert "$env:SHARED_MEMORY_TOKEN" in hook["command_windows"], event
    assert "git rev-parse --show-cdup" in before_edit["command_windows"]


# What Codex runs a hook's command_windows with: PowerShell 7 where it is installed (#275, seen in Codex 0.162.1), and
# Windows PowerShell on a machine without it. Neither is cmd.exe.
POWERSHELLS = [shell for shell in ("pwsh", "powershell") if shutil.which(shell)]


def codex_windows_hook(
    company: Company, files: list[dict[str, Any]], event: str, payload: dict[str, Any], shell: str, cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run one of Codex's generated Windows hook commands the way Codex runs it."""
    hooks = tomllib.loads(by_path(files)[".codex/config.toml"]["contents"])["hooks"]
    command = hooks[event][0]["hooks"][0]["command_windows"]
    return subprocess.run(
        [shell, "-NoProfile", "-Command", command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=cwd,
        env={**os.environ, "SHARED_MEMORY_TOKEN": company.owner_token},
    )


@pytest.mark.skipif(not POWERSHELLS, reason="Codex runs its Windows hooks in PowerShell, which isn't here")
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_codexs_windows_hooks_brief_a_session_in_powershell(company: Company, tmp_path: Path, shell: str) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    pinned(company.owner().in_project(created["project_id"], "billing-api"), "Use pnpm, not npm", "We use pnpm for every package.")
    payload = {"session_id": "codex-1", "cwd": str(tmp_path), "hook_event_name": "SessionStart", "source": "startup"}

    ran = codex_windows_hook(company, created["files"], "SessionStart", payload, shell, tmp_path)

    assert ran.returncode == 0, ran.stderr
    assert "Use pnpm, not npm" in json.loads(ran.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.skipif(not POWERSHELLS, reason="Codex runs its Windows hooks in PowerShell, which isn't here")
@pytest.mark.skipif(shutil.which("git") is None, reason="the root is git's answer")
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_codexs_windows_before_edit_hook_started_in_a_subfolder_locks_from_the_repositorys_root(
    company: Company, tmp_path: Path, shell: str
) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    payload = {
        "session_id": "codex-1",
        "cwd": str(tmp_path / "src"),
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n*** Update File: sub.py\n@@\n-a\n+b\n*** End Patch"},
    }

    ran = codex_windows_hook(company, created["files"], "PreToolUse", payload, shell, tmp_path / "src")

    assert ran.returncode == 0, ran.stderr
    dana = member(company, project, "emp-2", "Dana Dev")
    held = dana.hook_payload(
        "before-edit",
        {
            "session_id": "dana-1",
            "cwd": str(tmp_path),
            "hook_event_name": "PreToolUse",
            **edit_tool(str(tmp_path / "src" / "sub.py")),
        },
    )
    assert held["hookSpecificOutput"]["permissionDecision"] == "deny", "Codex's lock is named src/sub.py"


@pytest.mark.skipif(not POWERSHELLS, reason="Codex runs its Windows hooks in PowerShell, which isn't here")
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_codexs_windows_hooks_leave_the_session_alone_when_the_server_is_down(
    company: Company, tmp_path: Path, shell: str
) -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        down = f"http://127.0.0.1:{closed.getsockname()[1]}"
    files = connection_kit(
        server_url=down, marketplace="m", project_id="billing-1", project_name="Billing", repository="billing-api"
    )
    payload = {"session_id": "codex-1", "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit", "prompt": "hi"}

    ran = codex_windows_hook(company, files, "UserPromptSubmit", payload, shell, tmp_path)

    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == ""


def test_gemini_runs_both_its_hooks_through_one_script_that_suits_every_machine(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])
    hooks = json.loads(files[".gemini/settings.json"]["contents"])["hooks"]
    script = files[".gemini/hooks/shared-memory.mjs"]

    assert hooks["SessionStart"][0]["hooks"][0]["command"] == "node .gemini/hooks/shared-memory.mjs session-start"
    assert hooks["BeforeAgent"][0]["hooks"][0]["command"] == "node .gemini/hooks/shared-memory.mjs prompt-submitted"
    assert hooks["BeforeTool"][0]["matcher"] == ".*", "the hook before a tool runs on every tool (ADR-0025)"
    assert hooks["AfterTool"][0]["matcher"] == ".*"
    assert hooks["AfterTool"][0]["hooks"][0]["command"] == "node .gemini/hooks/shared-memory.mjs after-tool"
    assert hooks["BeforeTool"][0]["hooks"][0]["command"] == "node .gemini/hooks/shared-memory.mjs before-edit"
    assert hooks["SessionEnd"][0]["hooks"][0]["command"] == "node .gemini/hooks/shared-memory.mjs session-end"
    assert "GEMINI_PROJECT_DIR" in script["contents"]
    assert (script["agent"], script["action"]) == ("Gemini CLI", "create")
    assert "process.env.SHARED_MEMORY_TOKEN" in script["contents"]
    assert f"{company.server.url}/hooks" in script["contents"]


def test_copilot_cli_is_briefed_by_the_server_itself_with_no_shell_command(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    file = by_path(created["files"])[".github/hooks/shared-memory.json"]
    hooks = json.loads(file["contents"])["hooks"]

    briefing = hooks["sessionStart"][0]

    assert file["agent"] == "GitHub Copilot"
    assert briefing["type"] == "http"
    assert briefing["url"] == f"{company.server.url}/hooks/session-start?format=copilot-cli"
    assert briefing["headers"]["Authorization"] == "Bearer ${SHARED_MEMORY_TOKEN}"
    assert briefing["allowedEnvVars"] == ["SHARED_MEMORY_TOKEN"]
    assert "userPromptSubmitted" not in hooks


def test_copilot_cli_asks_the_server_before_its_edit_tools_and_as_a_session_ends(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    hooks = json.loads(by_path(created["files"])[".github/hooks/shared-memory.json"]["contents"])["hooks"]

    (before_edit,), (after,), (end,) = hooks["preToolUse"], hooks["postToolUse"], hooks["sessionEnd"]

    assert "matcher" not in before_edit and "matcher" not in after, "every tool call (ADR-0025)"
    assert after["url"] == f"{company.server.url}/hooks/after-tool?format=copilot-cli"
    assert (before_edit["type"], end["type"]) == ("http", "http"), "a hook that posts lets the edit through on failure"
    assert before_edit["url"] == f"{company.server.url}/hooks/before-edit?format=copilot-cli"
    assert before_edit["timeoutSec"] == 3
    assert end["url"] == f"{company.server.url}/hooks/session-end?format=copilot-cli"
    for hook in (before_edit, end):
        assert hook["headers"]["Authorization"] == "Bearer ${SHARED_MEMORY_TOKEN}"
        assert hook["headers"]["X-Shared-Memory-Repository"] == "billing-api"


def test_an_agent_that_reads_claude_codes_settings_runs_each_hook_once(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])
    devin = json.loads(files[".devin/hooks.v1.json"]["contents"])
    cursor = json.loads(files[".cursor/hooks.json"]["contents"])["hooks"]

    assert "hooks" not in json.loads(files[".claude/settings.json"]["contents"])
    assert "hooks" not in json.loads(files[".vscode/mcp.json"]["contents"])
    for event, entries in (*devin.items(), *cursor.items()):
        assert len(entries) == 1 and len(entries[0].get("hooks", [1])) == 1, event
    for endpoint in ("session-start", "prompt-submitted", "before-edit", "session-end"):
        posting = [path for path, file in files.items() if f"/hooks/{endpoint}" in file["contents"]]
        assert len([path for path in posting if path.startswith(".devin/")]) == 1, endpoint
        assert len([path for path in posting if path.startswith(".cursor/")]) <= 1, endpoint


#: Where each agent's kit keeps its before-edit hook, and what in that file shows the hook is there and gives up at
#: about 3 seconds. Cline's is a script per shell.
BEFORE_EDIT_HOOKS = {
    "Codex": (".codex/config.toml", "--max-time 3 "),
    "GitHub Copilot": (".github/hooks/shared-memory.json", '"timeoutSec": 3'),
    "Gemini CLI": (".gemini/hooks/shared-memory.mjs", "? 5 : 3"),
    "Cursor": (".cursor/hooks.json", "--max-time 3 "),
    "Devin Desktop": (".devin/hooks.v1.json", "--max-time 3 "),
    "Cline": (".clinerules/hooks/PreToolUse", "--max-time 3 "),
}


def test_every_agent_that_can_refuse_an_edit_has_the_before_edit_hook_in_its_own_file(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    for agent, (path, gives_up) in BEFORE_EDIT_HOOKS.items():
        assert files[path]["agent"] == agent
        hooked = files[path]["contents"] + files[".gemini/settings.json"]["contents"] * (agent == "Gemini CLI")
        assert "before-edit" in hooked, agent
        assert gives_up in files[path]["contents"], agent
        assert company.owner_token not in files[path]["contents"], agent
    assert "-TimeoutSec 3 " in files[".clinerules/hooks/PreToolUse.ps1"]["contents"]


def test_an_agent_with_no_before_edit_hook_is_told_its_locks_are_guidance_only(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    assert "before-edit" not in files[".vscode/mcp.json"]["contents"]
    assert "locks are guidance only" in files[".vscode/mcp.json"]["how"]
    assert "locks are guidance only" in files[".cursor/hooks.json"]["how"], "on Windows, where Cursor's hooks don't run"


def test_the_member_connecting_an_agent_with_no_hooks_is_told_sessions_that_talk_are_limited_there(
    company: Company,
) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    for path, agent in ((".vscode/mcp.json", "Copilot in VS Code"), (".cursor/hooks.json", "Cursor on Windows")):
        how = files[path]["how"]
        assert f"Sessions that talk are limited in {agent}" in how, path
        assert "can't be gated" in how, path
    assert "Sessions that talk" not in files[".github/hooks/shared-memory.json"]["how"], "Copilot CLI has hooks"


def test_an_agent_with_no_hooks_is_told_to_respect_a_gate_itself(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    for path in ("AGENTS.md", ".cursor/rules/shared-memory.mdc", ".agents/skills/shared-memory/SKILL.md"):
        said = " ".join(files[path]["contents"].split())
        assert "Copilot in VS Code and Cursor on Windows have no hooks" in said, path
        assert "respect a gate yourself" in said, path
        assert "edit no file of that work until it lifts" in said, path
        assert "`notices`" in said, path


def test_only_an_agent_with_no_before_edit_hook_is_told_to_take_a_lock_before_every_edit(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])
    hooked = "Claude Code, Codex, Copilot CLI, Gemini CLI, Cursor on macOS and Linux, Devin Desktop and Cline"
    unhooked = "In any other coding agent (Copilot in VS Code, Cursor on Windows), call `take_lock`"

    for path in ("AGENTS.md", ".cursor/rules/shared-memory.mdc", ".agents/skills/shared-memory/SKILL.md"):
        said = " ".join(files[path]["contents"].split())
        assert f"A before-edit hook takes each file's lock for you in {hooked}." in said, path
        assert unhooked in said, path
        assert said.count("before you edit") == 1, path


def test_cursor_asks_the_server_before_its_write_tool_and_as_a_session_ends(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    hooks = json.loads(by_path(created["files"])[".cursor/hooks.json"]["contents"])["hooks"]

    (before_edit,), (after,), (end,) = hooks["preToolUse"], hooks["postToolUse"], hooks["sessionEnd"]

    assert "matcher" not in before_edit and "matcher" not in after, "every tool call (ADR-0025)"
    assert f"{company.server.url}/hooks/after-tool?format=cursor" in after["command"]
    assert f"{company.server.url}/hooks/before-edit?format=cursor" in before_edit["command"]
    assert before_edit["command"].endswith("|| echo '{}'"), "Cursor blocks a tool whose hook answers nothing readable"
    assert before_edit["timeout"] == 4
    assert f"{company.server.url}/hooks/session-end?format=cursor" in end["command"]


def pinned(session: Session, title: str, body: str) -> str:
    """A project memory in this project's briefing, so a hook has something to bring back."""
    personal = session.call("remember", title=title, summary=f"{title}.", type="convention", body=body)["path"]
    result = session.call("promote", path=personal, level="project")
    if result["status"] == "similar_memories":
        keep = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call(
            "promote", path=personal, level="project", reference=result["reference"], resolutions=keep
        )
    path: str = result["path"]
    session.call("pin", path=path)
    return path


@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_the_script_geminis_hooks_run_brings_back_the_briefing(company: Company, tmp_path: Path) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    session = company.owner().in_project(created["project_id"], "billing-api")
    pinned(session, "Use pnpm, not npm", "We use pnpm for every package.")
    script = tmp_path / "shared-memory.mjs"
    script.write_text(by_path(created["files"])[".gemini/hooks/shared-memory.mjs"]["contents"], encoding="utf-8")

    ran = subprocess.run(
        ["node", str(script), "session-start"],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "SHARED_MEMORY_TOKEN": company.owner_token},
    )

    assert ran.returncode == 0, ran.stderr
    assert "Use pnpm, not npm" in json.loads(ran.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_geminis_hook_script_leaves_a_session_alone_when_it_cannot_reach_the_server(
    company: Company, tmp_path: Path
) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    script = tmp_path / "shared-memory.mjs"
    contents = by_path(created["files"])[".gemini/hooks/shared-memory.mjs"]["contents"]
    script.write_text(contents.replace(company.server.url, "http://127.0.0.1:1"), encoding="utf-8")

    ran = subprocess.run(
        ["node", str(script), "prompt-submitted"],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "which package manager do we use?"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "SHARED_MEMORY_TOKEN": company.owner_token},
    )

    assert (ran.returncode, ran.stdout) == (0, "")


#: The board habits every agent is given, one marker each: add a card for follow-up work and say so, claim only when
#: asked (the top card of the highest priority on "take the next card"), Done only on the member's word, the draft
#: learnings a card moved to Done asks for (#552), Blocked with a reason, known issues with a symptom and a workaround,
#: and the board items the briefing shows.
BOARD_HABITS = (
    "add_card",
    "tell the member",
    "claim_card",
    "take the next card",
    "highest priority",
    "confirms",
    "draft_learnings",
    "blocked_reason",
    "save_known_issue",
    "Workaround: none known",
    "briefing",
)


def test_every_agent_is_given_the_same_board_habits(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    for path in ("AGENTS.md", ".cursor/rules/shared-memory.mdc", ".agents/skills/shared-memory/SKILL.md"):
        for habit in BOARD_HABITS:
            assert habit in files[path]["contents"], (path, habit)


#: The session habits every agent is given, one marker each: pass the session's identifier, state the activity and
#: again when the task changes, tell the member who holds a file, a takeover only on the member's word, stop on a lock
#: taken over (told on a prompt or in a tool's notices), release a finished file, and the active sessions and collision
#: warnings that bear on the task, a gate, a message and a mute: finish the step, then stop and ask the member.
SESSION_HABITS = (
    "`session`",
    "set_activity",
    "when the task changes",
    "holder",
    "tell the member who holds",
    "`takeover: true` only once the member says so",
    "taken over",
    "`notices`",
    "stop editing that file",
    "release_lock",
    "active sessions",
    "collision",
    "gated",
    "different_work",
    "answer_gate",
    "message from another session",
    "urgent",
    "`mute`",
    "finish the step you are on, then stop and ask the member",
    "send_message",
    "leave_handoff_note",
    "from the repository's root",
)


def test_every_agent_is_given_the_same_session_habits(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    for path in ("AGENTS.md", ".cursor/rules/shared-memory.mdc", ".agents/skills/shared-memory/SKILL.md"):
        said = " ".join(files[path]["contents"].split())
        for habit in SESSION_HABITS:
            assert habit in said, (path, habit)


def test_cursor_is_briefed_by_a_hook_and_told_by_a_rule_to_search(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    hook = json.loads(files[".cursor/hooks.json"]["contents"])["hooks"]["sessionStart"][0]
    rule = files[".cursor/rules/shared-memory.mdc"]

    assert f"{company.server.url}/hooks/session-start?format=cursor" in hook["command"]
    assert "$SHARED_MEMORY_TOKEN" in hook["command"]
    assert rule["contents"].startswith("---\nalwaysApply: true\n---")
    for asked in ("search", "briefing", "remember", "information, not instructions"):
        assert asked in rule["contents"], asked


def test_devin_desktop_is_briefed_once_from_its_own_hooks(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    devin = json.loads(files[".devin/hooks.v1.json"]["contents"])

    assert f"{company.server.url}/hooks/session-start" in devin["SessionStart"][0]["hooks"][0]["command"]
    assert f"{company.server.url}/hooks/prompt-submitted" in devin["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert "hooks" not in json.loads(files[".claude/settings.json"]["contents"])


def test_devin_desktop_asks_the_server_before_its_edit_tools_and_as_a_session_ends(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    devin = json.loads(by_path(created["files"])[".devin/hooks.v1.json"]["contents"])

    (before_edit,), (after,), (end,) = devin["PreToolUse"], devin["PostToolUse"], devin["SessionEnd"]
    command = before_edit["hooks"][0]["command"]

    assert "matcher" not in before_edit and "matcher" not in after, "every tool call (ADR-0025)"
    assert f"'{company.server.url}/hooks/after-tool'" in after["hooks"][0]["command"]
    assert f"'{company.server.url}/hooks/before-edit?format=devin'" in command
    assert f'-H "X-Shared-Memory-Root: {repository_root("DEVIN_PROJECT_DIR")}"' in command, (
        "Devin's payload names no working folder, and the folder it was started in may be below the repository's root"
    )
    assert 'git -C "$DEVIN_PROJECT_DIR" rev-parse --show-cdup' in command
    assert before_edit["hooks"][0]["timeout"] == 4
    assert f"{company.server.url}/hooks/session-end" in end["hooks"][0]["command"]


def test_cline_gets_a_hook_script_for_each_shell_it_runs_them_in(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    for event, endpoint in (
        ("TaskStart", "session-start"),
        ("UserPromptSubmit", "prompt-submitted"),
        ("PreToolUse", "before-edit"),
        ("TaskComplete", "session-end"),
        ("TaskCancel", "session-end"),
    ):
        posix = files[f".clinerules/hooks/{event}"]
        windows = files[f".clinerules/hooks/{event}.ps1"]

        assert posix["contents"].startswith("#!/bin/sh"), event
        assert f"{company.server.url}/hooks/{endpoint}?format=cline" in posix["contents"], event
        assert "$SHARED_MEMORY_TOKEN" in posix["contents"], event
        assert f"{company.server.url}/hooks/{endpoint}?format=cline" in windows["contents"], event
        assert "$env:SHARED_MEMORY_TOKEN" in windows["contents"], event


def cline_hook_answer(company: Company, tmp_path: Path, shell: list[str], name: str) -> dict[str, Any]:
    """Run one of Cline's generated hook scripts the way Cline runs it, and return what it printed."""
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    session = company.owner().in_project(created["project_id"], "billing-api")
    pinned(session, "Use pnpm, not npm", "We use pnpm for every package.")
    script = tmp_path / name
    script.write_text(by_path(created["files"])[f".clinerules/hooks/{name}"]["contents"], encoding="utf-8")

    ran = subprocess.run(
        [*shell, str(script)],
        input=json.dumps({"hookName": "TaskStart", "taskId": "task-1", "clineVersion": "4.1.20"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "SHARED_MEMORY_TOKEN": company.owner_token},
    )

    assert ran.returncode == 0, ran.stderr
    answer: dict[str, Any] = json.loads(ran.stdout)
    return answer


@pytest.mark.skipif(shutil.which("sh") is None, reason="Cline runs these hooks in a POSIX shell, which isn't here")
def test_clines_hook_script_briefs_a_task_without_cancelling_it(company: Company, tmp_path: Path) -> None:
    answer = cline_hook_answer(company, tmp_path, ["sh"], "TaskStart")

    assert answer["cancel"] is False
    assert "Use pnpm, not npm" in answer["contextModification"]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="Cline runs its Windows hooks in PowerShell, which isn't here")
def test_clines_windows_hook_script_briefs_a_task_without_cancelling_it(company: Company, tmp_path: Path) -> None:
    answer = cline_hook_answer(company, tmp_path, ["pwsh", "-NoProfile", "-File"], "TaskStart.ps1")

    assert answer["cancel"] is False
    assert "Use pnpm, not npm" in answer["contextModification"]


#: A plugin's MCP tool is named `mcp__plugin_<plugin>_<server>__<tool>`; both the plugin and its server are `shared-memory`.
SEARCH_TOOLS = [f"mcp__plugin_shared-memory_shared-memory__{tool}" for tool in ("search", "read", "list", "tree")]


def test_the_claude_code_plugin_ships_a_memory_search_subagent_that_can_only_read_memory() -> None:
    plugin = REPO_ROOT / "plugin"
    text = (plugin / "agents" / "memory-search.md").read_text(encoding="utf-8")
    _, frontmatter, prompt = text.split("---\n", 2)
    fields = dict(line.split(": ", 1) for line in frontmatter.strip().splitlines())

    assert fields["name"] == "memory-search"
    assert fields["description"]
    assert [tool.strip() for tool in fields["tools"].split(",")] == SEARCH_TOOLS
    assert "path" in prompt and "never save" in prompt.lower()

    name = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["name"]
    server = next(iter(json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]))
    assert all(tool.startswith(f"mcp__plugin_{name}_{server}__") for tool in SEARCH_TOOLS)


def test_the_skill_says_when_to_hand_a_search_to_the_memory_search_subagent() -> None:
    skill = (REPO_ROOT / "plugin" / "skills" / "shared-memory" / "SKILL.md").read_text(encoding="utf-8")
    finding = skill.split("## Finding memory", 1)[1].split("\n## ", 1)[0]

    assert "memory-search" in finding


# The hook before every tool call names the session's branch (ADR-0025)


def kit_files() -> dict[str, str]:
    """The connection kit's files by path, for a server that need not be running."""
    files = connection_kit(
        server_url="https://memory.example.com",
        marketplace="raven-memory/shared-memory",
        project_id="billing-3f2a",
        project_name="Billing",
        repository="billing-api",
    )
    return {file["path"]: file["contents"] for file in files}


def codex_before_tool(files: dict[str, str], field: str) -> str:
    command: str = tomllib.loads(files[".codex/config.toml"])["hooks"]["PreToolUse"][0]["hooks"][0][field]
    return command


#: Where each agent's kit keeps what its hook before a tool runs, and what in it names the session's branch.
NAMES_THE_BRANCH: dict[str, tuple[Callable[[dict[str, str]], str], str]] = {
    "Codex": (
        lambda files: codex_before_tool(files, "command"),
        f'-H "X-Shared-Memory-Branch: {working_folder_branch()}"',
    ),
    "Codex on Windows": (
        lambda files: codex_before_tool(files, "command_windows"),
        "$headers['X-Shared-Memory-Branch']",
    ),
    "Cursor": (
        lambda files: json.loads(files[".cursor/hooks.json"])["hooks"]["preToolUse"][0]["command"],
        f'-H "X-Shared-Memory-Branch: {working_folder_branch()}"',
    ),
    "Devin Desktop": (
        lambda files: json.loads(files[".devin/hooks.v1.json"])["PreToolUse"][0]["hooks"][0]["command"],
        f'-H "X-Shared-Memory-Branch: {repository_branch("DEVIN_PROJECT_DIR")}"',
    ),
    "Cline": (
        lambda files: files[".clinerules/hooks/PreToolUse"],
        f'-H "X-Shared-Memory-Branch: {working_folder_branch()}"',
    ),
    "Cline on Windows": (
        lambda files: files[".clinerules/hooks/PreToolUse.ps1"],
        "$headers['X-Shared-Memory-Branch']",
    ),
    "Gemini CLI": (lambda files: files[".gemini/hooks/shared-memory.mjs"], '"X-Shared-Memory-Branch"'),
}


@pytest.mark.parametrize("agent", list(NAMES_THE_BRANCH))
def test_every_agents_hook_before_a_tool_names_the_sessions_branch(agent: str) -> None:
    command, names = NAMES_THE_BRANCH[agent]

    written = command(kit_files())

    assert names in written
    assert "symbolic-ref --short -q HEAD" in written or '"symbolic-ref", "--short", "-q", "HEAD"' in written


def test_only_the_hook_before_a_tool_names_the_branch() -> None:
    files = kit_files()

    for path in (".clinerules/hooks/TaskStart", ".clinerules/hooks/UserPromptSubmit", ".clinerules/hooks/TaskComplete"):
        assert "X-Shared-Memory-Branch" not in files[path], path
    devin = json.loads(files[".devin/hooks.v1.json"])
    assert "X-Shared-Memory-Branch" not in devin["PostToolUse"][0]["hooks"][0]["command"]


def test_copilot_cli_posts_without_a_shell_so_names_no_branch() -> None:
    hooks = json.loads(kit_files()[".github/hooks/shared-memory.json"])["hooks"]

    assert "X-Shared-Memory-Branch" not in hooks["preToolUse"][0]["headers"]


# Every kit's session-start hook gives its machine's UTC offset (#592), which the server keeps on the session for the
# clock times in its warnings while its member has no time zone. These run each hook in a machine set to India's time.
INDIA = "Asia/Kolkata"
INDIA_OFFSET = "X-Shared-Memory-Utc-Offset: +0530"


def codex_session_start(files: dict[str, str], field: str) -> str:
    command: str = tomllib.loads(files[".codex/config.toml"])["hooks"]["SessionStart"][0]["hooks"][0][field]
    return command


#: Where each kit keeps what its session-start hook runs in a POSIX shell.
POSIX_SESSION_START: dict[str, Callable[[dict[str, str]], str]] = {
    "Claude Code": lambda files: claude_code_session_start_hook(),
    "Codex": lambda files: codex_session_start(files, "command"),
    "Cursor": lambda files: json.loads(files[".cursor/hooks.json"])["hooks"]["sessionStart"][0]["command"],
    "Devin Desktop": lambda files: json.loads(files[".devin/hooks.v1.json"])["SessionStart"][0]["hooks"][0]["command"],
    "Cline": lambda files: files[".clinerules/hooks/TaskStart"],
}

#: Where each kit keeps what its session-start hook runs in PowerShell, and how PowerShell runs it.
POWERSHELL_SESSION_START: dict[str, tuple[Callable[[dict[str, str]], str], str]] = {
    "Codex on Windows": (lambda files: codex_session_start(files, "command_windows"), "-Command"),
    "Cline on Windows": (lambda files: files[".clinerules/hooks/TaskStart.ps1"], "-File"),
}


@pytest.mark.parametrize("agent", list(POSIX_SESSION_START))
def test_every_agents_session_start_hook_gives_its_machines_utc_offset(agent: str, tmp_path: Path) -> None:
    command = POSIX_SESSION_START[agent](kit_files())

    ran = subprocess.run(
        ["sh", "-c", command],
        input=SESSION_START,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **without_plugin_settings(),
            **recording_curl(tmp_path),
            "TZ": INDIA,
            "SHARED_MEMORY_TOKEN": "smt_test",
            "CLAUDE_PLUGIN_OPTION_PERSONAL_TOKEN": "smt_test",
            "CLAUDE_PLUGIN_OPTION_SERVER_URL": "https://memory.example.com",
        },
    )

    assert ran.returncode == 0, ran.stderr
    assert INDIA_OFFSET in (tmp_path / "arguments").read_text(encoding="utf-8").split("\n")


@pytest.mark.parametrize("agent", list(POWERSHELL_SESSION_START))
def test_every_agents_session_start_hook_in_powershell_gives_its_machines_utc_offset(agent: str) -> None:
    command, _ = POWERSHELL_SESSION_START[agent]

    assert "$headers['X-Shared-Memory-Utc-Offset'] = (Get-Date -Format zzz)" in command(kit_files())


def test_only_the_session_start_hook_gives_the_utc_offset() -> None:
    files = kit_files()

    for path in (
        ".clinerules/hooks/UserPromptSubmit",
        ".clinerules/hooks/PreToolUse",
        ".clinerules/hooks/TaskComplete",
        ".clinerules/hooks/PreToolUse.ps1",
    ):
        assert "X-Shared-Memory-Utc-Offset" not in files[path], path
    assert "X-Shared-Memory-Utc-Offset" not in codex_before_tool(files, "command")
    assert "X-Shared-Memory-Utc-Offset" not in codex_before_tool(files, "command_windows")


def test_copilot_cli_posts_without_a_shell_so_gives_no_utc_offset() -> None:
    hooks = json.loads(kit_files()[".github/hooks/shared-memory.json"])["hooks"]

    assert "X-Shared-Memory-Utc-Offset" not in hooks["sessionStart"][0]["headers"]


@contextmanager
def recording_server() -> Iterator[tuple[str, list[dict[str, str]]]]:
    """A server that answers every POST with `{}` and records each one's headers: its address and what it heard."""
    heard: list[dict[str, str]] = []

    class Recording(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802  # the name http.server calls
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            heard.append({name.lower(): value for name, value in self.headers.items()})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    listening = ThreadingHTTPServer(("127.0.0.1", 0), Recording)
    thread = threading.Thread(target=listening.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listening.server_address[1]}", heard
    finally:
        listening.shutdown()
        listening.server_close()


def kit_files_for(server_url: str) -> dict[str, str]:
    """The connection kit's files by path, for a server at this address."""
    files = connection_kit(
        server_url=server_url,
        marketplace="m",
        project_id="billing-3f2a",
        project_name="Billing",
        repository="billing-api",
    )
    return {file["path"]: file["contents"] for file in files}


@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_geminis_session_start_hook_gives_its_machines_utc_offset(tmp_path: Path) -> None:
    with recording_server() as (url, heard):
        script = tmp_path / "shared-memory.mjs"
        script.write_text(kit_files_for(url)[".gemini/hooks/shared-memory.mjs"], encoding="utf-8")

        ran = subprocess.run(
            ["node", str(script), "session-start"],
            input=SESSION_START,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "TZ": INDIA, "SHARED_MEMORY_TOKEN": "smt_test"},
        )

    assert ran.returncode == 0, ran.stderr
    assert [each.get("x-shared-memory-utc-offset") for each in heard] == ["+0530"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_geminis_hook_gives_a_utc_offset_west_of_utc_with_its_sign(tmp_path: Path) -> None:
    with recording_server() as (url, heard):
        script = tmp_path / "shared-memory.mjs"
        script.write_text(kit_files_for(url)[".gemini/hooks/shared-memory.mjs"], encoding="utf-8")

        subprocess.run(
            ["node", str(script), "session-start"],
            input=SESSION_START,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "TZ": "America/St_Johns", "SHARED_MEMORY_TOKEN": "smt_test"},
        )

    assert heard[0].get("x-shared-memory-utc-offset") in ("-0330", "-0230"), "Newfoundland, in or out of summer time"


@pytest.mark.skipif(not POWERSHELLS, reason="these hooks run in PowerShell, which isn't here")
@pytest.mark.parametrize("shell", POWERSHELLS)
@pytest.mark.parametrize("agent", list(POWERSHELL_SESSION_START))
def test_every_agents_powershell_session_start_hook_sends_its_machines_utc_offset(
    agent: str, shell: str, tmp_path: Path
) -> None:
    command, runs_with = POWERSHELL_SESSION_START[agent]
    with recording_server() as (url, heard):
        written = command(kit_files_for(url))
        if runs_with == "-File":
            script = tmp_path / "TaskStart.ps1"
            script.write_text(written, encoding="utf-8")
            written = str(script)

        ran = subprocess.run(
            [shell, "-NoProfile", runs_with, written],
            input=SESSION_START,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "TZ": INDIA, "SHARED_MEMORY_TOKEN": "smt_test"},
        )

    assert ran.returncode == 0, ran.stderr
    assert [each.get("x-shared-memory-utc-offset") for each in heard] == ["+05:30"]


#: The kits whose hook before a tool takes no added context, and the hook after a tool each hears its news on.
HEARS_AFTER_A_TOOL: dict[str, Callable[[dict[str, str]], str]] = {
    "Gemini CLI": lambda files: json.loads(files[".gemini/settings.json"])["hooks"]["AfterTool"][0]["hooks"][0]["command"],
    "GitHub Copilot": lambda files: json.loads(files[".github/hooks/shared-memory.json"])["hooks"]["postToolUse"][0]["url"],
    "Cursor": lambda files: json.loads(files[".cursor/hooks.json"])["hooks"]["postToolUse"][0]["command"],
    "Devin Desktop": lambda files: json.loads(files[".devin/hooks.v1.json"])["PostToolUse"][0]["hooks"][0]["command"],
}  # fmt: skip


@pytest.mark.parametrize("agent", list(HEARS_AFTER_A_TOOL))
def test_an_agent_whose_hook_before_a_tool_takes_no_context_hears_its_news_after_the_tool(agent: str) -> None:
    assert "after-tool" in HEARS_AFTER_A_TOOL[agent](kit_files())


def test_the_agents_whose_hook_before_a_tool_takes_context_have_no_hook_after_one() -> None:
    files = kit_files()

    assert "PostToolUse" not in tomllib.loads(files[".codex/config.toml"])["hooks"]
    assert not any("PostToolUse" in path for path in files), "Cline"
    plugin = json.loads((REPO_ROOT / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert "PostToolUse" not in plugin


def test_the_cursor_hook_after_a_tool_answers_something_cursor_can_read_when_the_server_does_not() -> None:
    after = json.loads(kit_files()[".cursor/hooks.json"])["hooks"]["postToolUse"][0]

    assert after["command"].endswith("|| echo '{}'")
    assert after["timeout"] == 4 and "--max-time 3 " in after["command"]


def test_every_agents_guidance_says_news_can_arrive_mid_turn() -> None:
    files = kit_files()

    for path in ("AGENTS.md", ".cursor/rules/shared-memory.mdc", ".agents/skills/shared-memory/SKILL.md"):
        said = " ".join(files[path].split())
        assert "can arrive mid-turn" in said or "in the middle of a turn" in said, path
        assert "then stop and tell the member" in said, path


# Claude Code stands by with a background command the skill gives (ADR-0027, #526)


class HeaderListener:
    """A local HTTP listener that records each request's path and Authorization header, and answers {}."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []
        seen = self.seen

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802  # the name http.server calls
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self._answer()

            def do_GET(self) -> None:  # noqa: N802
                self._answer()

            def _answer(self) -> None:
                seen.append((self.path, self.headers.get("Authorization", "")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def claude_code_skill() -> str:
    return (REPO_ROOT / "plugin" / "skills" / "shared-memory" / "SKILL.md").read_text(encoding="utf-8")


def standing_by_section(skill: str) -> str:
    return skill.split("## Standing by", 1)[1].split("\n## ", 1)[0]


def standby_command(skill: str) -> str:
    """The background command the skill gives for standing by, as the agent copies it, `<session>` and all."""
    return standing_by_section(skill).split("```sh\n", 1)[1].split("\n```", 1)[0]


#: When Claude Code stands by and what it does with the answer, one marker each: run in the background, stand by when
#: an edit is refused as gated, after an urgent message and after a message whose answer the member wants, at most once
#: more after an empty answer, retry once after a few seconds then say the server isn't answering, show the member
#: the answer and ask what to do, and show the warning the answer's `member` holds first (#590).
STANDBY_HABITS = (
    "run_in_background",
    "an edit is refused as gated",
    "urgent message",
    "the member wants its answer",
    "at most once more",
    "a few seconds",
    "Shared Memory isn't answering",
    "show the member",
    "ask what to do",
    "`member`",
)


#: What the skill says of a warning (#586), one marker each: the lead-in it comes under, shown first, word for word, never
#: paraphrased or left out, the fence kept, the lines after it the agent's, each gate's reply words, and a reply word
#: being the member's decision.
WARNING_HABITS = (
    "Show your member this first, word for word:",
    "Show the member the heading and the box first",
    "never paraphrase it, shorten it or leave it out",
    "keep the fence",
    "The lines after the warning are for you alone",
    "*wait* (stand by), *different work* and *pick something else*",
    "*agree* and *refuse*",
    "that is their decision",
)


def test_the_skill_tells_the_agent_to_show_a_warning_word_for_word_first_and_take_a_reply_word_as_the_members_decision() -> (
    None
):
    said = " ".join(claude_code_skill().split())

    for habit in WARNING_HABITS:
        assert habit in said, habit


def test_the_skill_tells_claude_code_when_to_stand_by_and_what_to_do_with_the_answer() -> None:
    said = " ".join(standing_by_section(claude_code_skill()).split())

    for habit in STANDBY_HABITS:
        assert habit in said, habit


def test_claude_codes_standby_command_reaches_the_server_as_the_plugins_hooks_do() -> None:
    command = standby_command(claude_code_skill())
    hooks = (REPO_ROOT / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8")

    assert "$CLAUDE_PLUGIN_OPTION_SERVER_URL/hooks/standby" in command
    assert '-H "@$SHARED_MEMORY_HEADER_FILE"' in command
    assert "PERSONAL_TOKEN" not in command, "the token comes from the header file, not the environment"
    for read in (
        "X-Shared-Memory-Project: $SHARED_MEMORY_PROJECT",
        "X-Shared-Memory-Repository: $SHARED_MEMORY_REPOSITORY",
        "X-Shared-Memory-Agent: claude-code",
    ):
        assert read in command and read in hooks, read
    assert '"session_id":"<session>"' in command


def test_claude_codes_standby_command_sends_the_token_from_the_header_file_never_its_command_line(
    tmp_path: Path,
) -> None:
    token = "smt_never-on-the-command-line"
    listener = HeaderListener()
    header_file = tmp_path / "shared-memory.headers"
    header_file.write_text(f"Authorization: Bearer {token}\n", encoding="utf-8")
    command = standby_command(claude_code_skill()).replace("<session>", "test-session")
    try:
        ran = subprocess.run(
            ["sh", "-c", command],
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **without_plugin_settings(),
                "SHARED_MEMORY_HEADER_FILE": str(header_file),
                "CLAUDE_PLUGIN_OPTION_SERVER_URL": listener.url,
            },
        )
    finally:
        listener.stop()

    assert ran.returncode == 0, ran.stderr
    assert token not in command
    assert listener.seen == [("/hooks/standby", f"Bearer {token}")]


# Claude Code gives the plugin's settings only to the plugin's own hooks and MCP server, not to the agent's commands, so
# the session-start hook writes them to the file Claude Code reads before each of the agent's commands (CLAUDE_ENV_FILE).


def claude_code_session_start_hook() -> str:
    hooks = json.loads((REPO_ROOT / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    command: str = hooks["SessionStart"][0]["hooks"][0]["command"]
    return command


#: A token and an address with the characters a shell treats specially, which must come back exactly.
AWKWARD_TOKEN = 'smt_it\'s "odd" $HOME `id` \\ ; | & * ? \t end'
AWKWARD_SERVER_URL = "http://127.0.0.1:1/a b'c$d"
SESSION_START = json.dumps({"session_id": "test-session", "hook_event_name": "SessionStart", "source": "startup"})


def recording_curl(folder: Path) -> dict[str, str]:
    """The environment for a stand-in curl that records its arguments one per line in `folder` and answers `{}`."""
    shims = folder / "bin"
    shims.mkdir()
    curl = shims / "curl"
    curl.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SEEN/arguments\"\ncat > /dev/null\necho '{}'\n", encoding="utf-8"
    )
    curl.chmod(0o755)
    return {"PATH": f"{shims}{os.pathsep}{os.environ['PATH']}", "SEEN": str(folder)}


def without_plugin_settings() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CLAUDE_PLUGIN_OPTION_") and key != "CLAUDE_ENV_FILE"
    }


def run_session_start(
    tmp_path: Path, env_file: Path | None, token: str = AWKWARD_TOKEN, state: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Claude Code's session-start hook, with the awkward settings, a stand-in curl and its own state folder."""
    return subprocess.run(
        ["sh", "-c", claude_code_session_start_hook()],
        input=SESSION_START,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **without_plugin_settings(),
            **recording_curl(tmp_path),
            **({"CLAUDE_ENV_FILE": str(env_file)} if env_file else {}),
            "XDG_STATE_HOME": str(state or tmp_path / "state"),
            "CLAUDE_PLUGIN_OPTION_PERSONAL_TOKEN": token,
            "CLAUDE_PLUGIN_OPTION_SERVER_URL": AWKWARD_SERVER_URL,
        },
    )


def sourced(env_file: Path, *names: str) -> list[str]:
    """What the agent's commands see of these variables once Claude Code has sourced the environment file."""
    shown = " ".join(f'"${{{name}-unset}}"' for name in names)
    ran = subprocess.run(
        ["sh", "-c", f'. "$1"; printf \'%s\\n\' {shown}', "sh", str(env_file)],
        capture_output=True,
        text=True,
        timeout=30,
        env=without_plugin_settings(),
    )
    return ran.stdout.rstrip("\n").split("\n")


def test_claude_codes_session_start_hook_keeps_the_token_out_of_the_agents_environment(tmp_path: Path) -> None:
    env_file = tmp_path / "claude-env"
    env_file.write_text("export ALREADY_THERE='kept'\n", encoding="utf-8")

    ran = run_session_start(tmp_path, env_file)

    assert (ran.returncode, ran.stdout.strip(), ran.stderr) == (0, "{}", ""), "the briefing's answer, and nothing else"
    assert "smt_" not in env_file.read_text(encoding="utf-8")
    seen = sourced(env_file, "ALREADY_THERE", "CLAUDE_PLUGIN_OPTION_SERVER_URL", "CLAUDE_PLUGIN_OPTION_PERSONAL_TOKEN")
    assert seen == ["kept", AWKWARD_SERVER_URL, "unset"]
    arguments = (tmp_path / "arguments").read_text(encoding="utf-8").split("\n")
    assert [line for line in arguments if "smt_" in line] == [], "nor on the hook's own command line"
    [header_file] = sourced(env_file, "SHARED_MEMORY_HEADER_FILE")
    assert f"@{header_file}" in arguments, "its own request reads the token from the header file too"


def test_claude_codes_session_start_hook_keeps_one_header_file_per_server_whatever_the_token(tmp_path: Path) -> None:
    state = tmp_path / "state"
    for run, token in (("first", "smt_first"), ("second", "smt_second")):
        (tmp_path / run).mkdir()
        run_session_start(tmp_path / run, tmp_path / run / "claude-env", token=token, state=state)

    [header_file] = list((state / "shared-memory").glob("*.headers"))
    assert header_file.read_text(encoding="utf-8") == "Authorization: Bearer smt_second\n"
    assert "smt_" not in header_file.name


@pytest.mark.parametrize("header_file", ["gone", "empty"])
def test_claude_codes_standby_command_without_its_header_file_asks_for_a_new_session(
    tmp_path: Path, header_file: str
) -> None:
    if header_file == "empty":
        (tmp_path / "empty.headers").write_text("", encoding="utf-8")
    listener = HeaderListener()
    command = standby_command(claude_code_skill()).replace("<session>", "test-session")
    try:
        ran = subprocess.run(
            ["sh", "-c", command],
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **without_plugin_settings(),
                "SHARED_MEMORY_HEADER_FILE": str(tmp_path / f"{header_file}.headers"),
                "CLAUDE_PLUGIN_OPTION_SERVER_URL": listener.url,
            },
        )
    finally:
        listener.stop()

    assert "restart this session" in ran.stdout
    assert listener.seen == [], "nothing is sent without the token"


def test_claude_codes_session_start_hook_writes_a_header_file_only_its_owner_can_read(tmp_path: Path) -> None:
    env_file = tmp_path / "claude-env"

    run_session_start(tmp_path, env_file)

    [named] = sourced(env_file, "SHARED_MEMORY_HEADER_FILE")
    header_file = Path(named)
    assert header_file.is_file() and tmp_path / "state" in header_file.parents
    if os.name != "nt":
        assert stat.S_IMODE(header_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(header_file.parent.stat().st_mode) == 0o700
    listener = HeaderListener()
    try:
        subprocess.run(
            ["curl", "-s", "--max-time", "10", "-H", f"@{header_file}", f"{listener.url}/hooks/standby"],
            capture_output=True,
            timeout=30,
        )
    finally:
        listener.stop()
    assert listener.seen == [("/hooks/standby", f"Bearer {AWKWARD_TOKEN}")], "curl reads the token back exactly"


def test_claude_codes_session_start_hook_without_an_environment_file_only_briefs(tmp_path: Path) -> None:
    ran = run_session_start(tmp_path, None)

    assert (ran.returncode, ran.stdout.strip(), ran.stderr) == (0, "{}", "")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["arguments", "bin"], "and writes no header file"
    arguments = (tmp_path / "arguments").read_text(encoding="utf-8").split("\n")
    assert f"Authorization: Bearer {AWKWARD_TOKEN}" in arguments, "its request carries the token as before"


# Every other agent's kit says how it stands by (ADR-0027, #527): the background command first and the `stand_by` tool
# as its fallback where an agent's wake-up after its turn ends is not yet known, and the tool everywhere else, each
# call as long as the agent's tool timeout allows.

#: The kit file whose connect output (`how`) says how each agent that may be woken stands by.
STANDS_BY_IN_THE_BACKGROUND = {
    "Copilot in VS Code": ".vscode/mcp.json",
    "Copilot CLI": ".github/hooks/shared-memory.json",
    "Cursor on macOS and Linux": ".cursor/hooks.json",
}
#: The kit file whose connect output says how each tool agent stands by, and the seconds of each `stand_by` call.
STANDS_BY_WITH_THE_TOOL = {
    "Codex": (".codex/config.toml", 45),
    "Gemini CLI": (".gemini/settings.json", 300),
    "Cline": ("~/.cline/data/settings/cline_mcp_settings.json", 45),
    "Devin Desktop": (".devin/hooks.v1.json", 45),
    "Cursor on Windows": (".cursor/hooks.json", 45),
}
#: Where every agent but Claude Code is given its session habits.
GUIDANCE = ("AGENTS.md", ".cursor/rules/shared-memory.mdc")


def kit_how() -> dict[str, str]:
    """What the connect output says of each kit file, by path, its whitespace evened out."""
    files = connection_kit(
        server_url="https://memory.example.com",
        marketplace="raven-memory/shared-memory",
        project_id="billing-3f2a",
        project_name="Billing",
        repository="billing-api",
    )
    return {file["path"]: " ".join(file["how"].split()) for file in files}


@pytest.mark.parametrize("agent", list(STANDS_BY_IN_THE_BACKGROUND))
def test_the_connect_output_of_an_agent_that_may_be_woken_names_the_background_command_then_the_tool(
    agent: str,
) -> None:
    how = kit_how()[STANDS_BY_IN_THE_BACKGROUND[agent]]

    assert f"{agent} stands by with the background command" in how
    assert "for a POSIX shell and for PowerShell" in how
    assert "calls the stand_by tool instead" in how, "the fallback"


@pytest.mark.parametrize("agent", list(STANDS_BY_WITH_THE_TOOL))
def test_the_connect_output_of_a_tool_agent_names_the_stand_by_tool_and_the_length_its_timeout_allows(
    agent: str,
) -> None:
    path, seconds = STANDS_BY_WITH_THE_TOOL[agent]

    how = kit_how()[path]

    assert f"{agent} stands by with the stand_by tool, each call held up to {seconds} seconds" in how


def test_the_lengths_the_tool_agents_are_given_fit_the_servers_cap_and_each_agents_tool_timeout() -> None:
    given = {guidance_name(each.agent): each for each in STAND_BY_WITH_THE_TOOL}
    cap = Settings.from_env({}).standby_tool_cap_seconds

    assert {agent: each.seconds for agent, each in given.items()} == {
        agent: seconds for agent, (_, seconds) in STANDS_BY_WITH_THE_TOOL.items()
    }
    for each in STAND_BY_WITH_THE_TOOL:
        assert each.seconds <= cap, each.agent
        assert each.seconds == STAND_BY_SECONDS or each.allows is not None, f"{each.agent}: longer only where allowed"
        assert each.allows is None or each.seconds < each.allows, each.agent
    (cline,) = json.loads(kit_files()["~/.cline/data/settings/cline_mcp_settings.json"])["mcpServers"].values()
    assert cline["timeout"] == given["Cline"].allows, "the kit sets the timeout Cline's calls are held within"


def test_every_agents_guidance_names_each_agents_route_to_stand_by() -> None:
    files = kit_files()
    background = (
        "In Copilot in VS Code, Cursor on macOS and Linux and Copilot CLI, run the standby command below in the "
        "background"
    )
    tool = "In Codex, Gemini CLI, Cline, Devin Desktop, Cursor on Windows and any other coding agent, call `stand_by`"

    for path in GUIDANCE:
        said = " ".join(files[path].split())
        assert background in said, path
        assert "call `stand_by` instead" in said, (path, "the background agents' fallback")
        assert tool in said, path
        assert "`seconds` 300 in Gemini CLI and 45 in the others" in said, path
        assert "`wait_left_seconds` above 0, call it again" in said, path


#: When every agent stands by and what it does with the answer, as #526's STANDBY_HABITS say for Claude Code, less
#: Claude Code's own tool.
EVERY_AGENTS_STANDBY_HABITS = tuple(habit for habit in STANDBY_HABITS if habit != "run_in_background")


def test_every_agents_guidance_says_when_to_stand_by_and_what_to_do_with_the_answer() -> None:
    files = kit_files()

    for path in GUIDANCE:
        said = " ".join(files[path].split())
        for habit in EVERY_AGENTS_STANDBY_HABITS:
            assert habit in said, (path, habit)


def background_standby_commands(guidance: str) -> tuple[str, str]:
    """The background standby command a guidance file gives, for a POSIX shell and for PowerShell, `<session>` and
    all, as the agent copies it."""
    posix = guidance.split("```sh\n", 1)[1].split("\n```", 1)[0]
    powershell = guidance.split("```powershell\n", 1)[1].split("\n```", 1)[0]
    return posix, powershell


def test_the_background_standby_command_is_written_for_a_posix_shell_and_for_powershell() -> None:
    files = kit_files()
    posix, powershell = background_standby_commands(files["AGENTS.md"])

    assert background_standby_commands(files[".cursor/rules/shared-memory.mdc"]) == (posix, powershell)
    assert "-H 'X-Shared-Memory-Project: billing-3f2a' -H 'X-Shared-Memory-Repository: billing-api'" in posix
    assert "'X-Shared-Memory-Project' = 'billing-3f2a'; 'X-Shared-Memory-Repository' = 'billing-api'" in powershell
    for command in (posix, powershell):
        assert "'https://memory.example.com/hooks/standby'" in command
        assert """'{"session_id":"<session>"}'""" in command
        assert "'Shared Memory did not answer this standby.'" in command
    assert """printf 'header = "Authorization: Bearer %s"\\n' "$SHARED_MEMORY_TOKEN" | curl""" in posix
    assert 'Authorization = "Bearer $env:SHARED_MEMORY_TOKEN"' in powershell


def test_the_background_standby_command_is_held_as_long_as_claude_codes() -> None:
    posix, powershell = background_standby_commands(kit_files()["AGENTS.md"])
    claude_code = standby_command(claude_code_skill())

    seconds = claude_code.split("--max-time ", 1)[1].split()[0]
    assert f"--max-time {seconds} " in posix
    assert f"-TimeoutSec {seconds} " in powershell


def test_the_background_standby_command_never_puts_the_token_on_its_command_line(tmp_path: Path) -> None:
    token = "smt_never-on-the-command-line"
    shims = tmp_path / "bin"
    shims.mkdir()
    curl = shims / "curl"
    curl.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$SEEN/arguments"\ncat > "$SEEN/input"\n', encoding="utf-8")
    curl.chmod(0o755)
    posix, _ = background_standby_commands(kit_files()["AGENTS.md"])

    ran = subprocess.run(
        ["sh", "-c", posix.replace("<session>", "test-session")],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}",
            "SEEN": str(tmp_path),
            "SHARED_MEMORY_TOKEN": token,
        },
    )

    assert ran.returncode == 0, ran.stderr
    assert token not in (tmp_path / "arguments").read_text(encoding="utf-8")
    assert f"Authorization: Bearer {token}" in (tmp_path / "input").read_text(encoding="utf-8")


def without_the_token() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key != "SHARED_MEMORY_TOKEN"}


def test_the_background_standby_command_without_a_token_says_to_call_stand_by_instead(tmp_path: Path) -> None:
    posix, _ = background_standby_commands(kit_files()["AGENTS.md"])
    shims = tmp_path / "bin"
    shims.mkdir()
    curl = shims / "curl"
    curl.write_text('#!/bin/sh\ntouch "$SEEN/called"\n', encoding="utf-8")
    curl.chmod(0o755)

    ran = subprocess.run(
        ["sh", "-c", posix.replace("<session>", "test-session")],
        capture_output=True,
        text=True,
        timeout=30,
        env={**without_the_token(), "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}", "SEEN": str(tmp_path)},
    )

    assert (ran.returncode, ran.stderr) == (0, "")
    assert "call stand_by instead" in ran.stdout
    assert not (tmp_path / "called").exists(), "nothing is sent without a token"


@pytest.mark.skipif(not POWERSHELLS, reason="The background command for Windows runs in PowerShell, which isn't here")
@pytest.mark.parametrize("shell", POWERSHELLS)
def test_the_background_standby_command_in_powershell_without_a_token_says_to_call_stand_by_instead(shell: str) -> None:
    _, powershell = background_standby_commands(kit_files()["AGENTS.md"])

    ran = subprocess.run(
        [shell, "-NoProfile", "-Command", powershell.replace("<session>", "test-session")],
        capture_output=True,
        text=True,
        timeout=60,
        env=without_the_token(),
    )

    assert ran.returncode == 0, ran.stderr
    assert "call stand_by instead" in ran.stdout


def test_the_skill_names_each_agents_route_to_stand_by_and_the_tool_agents_lengths() -> None:
    said = " ".join(standing_by_section(claude_code_skill()).split())

    assert (
        "In Copilot in VS Code, Cursor on macOS and Linux and Copilot CLI, stand by with the background command" in said
    )
    assert "call the `stand_by` tool instead" in said
    assert (
        "In Codex, Gemini CLI, Cline, Devin Desktop, Cursor on Windows and any other coding agent, call `stand_by`"
        in said
    )
    assert "`seconds` 300 in Gemini CLI and 45 in the others" in said
    assert "`wait_left_seconds` above 0, call it again" in said


def test_the_skill_names_the_lengths_the_server_and_the_kit_hold_a_standby_to() -> None:
    """A limit is named once: the skill is static text, so this holds its numbers to the constants the server and the
    kit use."""
    skill = claude_code_skill()
    said = " ".join(standing_by_section(skill).split())
    (gemini,) = [each for each in STAND_BY_WITH_THE_TOOL if each.agent == GEMINI_CLI]

    assert f"--max-time {STANDBY_COMMAND_SECONDS} " in standby_command(skill)
    assert gemini.seconds == STAND_BY_TOOL_CAP_SECONDS
    assert f"`seconds` {STAND_BY_TOOL_CAP_SECONDS} in Gemini CLI and {STAND_BY_SECONDS} in the others" in said


def test_an_agent_with_no_route_to_stand_by_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="Claude Code"):
        stands_by(CLAUDE_CODE)
