"""Connecting a repository: the files each coding agent commits so its sessions reach the project."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.support import REPO_ROOT, Session, Team


def by_path(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {file["path"]: file for file in files}


def test_connecting_a_repository_gives_each_agent_the_files_it_commits(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]
    files = by_path(created["files"])

    claude = json.loads(files[".claude/settings.json"]["contents"])
    codex = tomllib.loads(files[".codex/config.toml"]["contents"])["mcp_servers"]["shared-memory"]

    assert files[".claude/settings.json"]["agent"] == "Claude Code"
    assert claude["env"] == {"SHARED_MEMORY_PROJECT": project, "SHARED_MEMORY_REPOSITORY": "billing-api"}
    assert files[".codex/config.toml"]["agent"] == "Codex"
    assert codex["url"] == f"{team.server.url}/mcp"
    assert codex["bearer_token_env_var"] == "SHARED_MEMORY_TOKEN"
    assert codex["http_headers"] == {"X-Shared-Memory-Project": project, "X-Shared-Memory-Repository": "billing-api"}


def test_every_agent_is_told_in_agents_md_how_to_use_the_projects_memory(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")

    section = by_path(created["files"])["AGENTS.md"]

    assert section["agent"] == "Every agent"
    assert section["action"] == "merge"
    for needed in (created["project_id"], "billing-api", "briefing", "search", "remember", "SHARED_MEMORY_TOKEN"):
        assert needed in section["contents"], needed


def test_the_skill_every_agent_reads_is_the_one_claude_code_ships(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")

    skill = by_path(created["files"])[".agents/skills/shared-memory/SKILL.md"]

    shipped = (REPO_ROOT / "plugin" / "skills" / "shared-memory" / "SKILL.md").read_text(encoding="utf-8")
    assert skill["contents"] == shipped
    assert skill["action"] == "create"


def test_no_connection_file_carries_a_personal_token(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")

    for file in created["files"]:
        assert team.owner_token not in file["contents"], file["path"]
        assert "smt_" not in file["contents"], file["path"]


def mcp_server(file: dict[str, Any], section: str = "mcpServers", name: str = "shared-memory") -> dict[str, Any]:
    server: dict[str, Any] = json.loads(file["contents"])[section][name]
    return server


def test_every_agent_with_a_repository_file_is_pointed_at_the_project(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]
    files = by_path(created["files"])
    expected = {"X-Shared-Memory-Project": project, "X-Shared-Memory-Repository": "billing-api"}

    vscode = mcp_server(files[".vscode/mcp.json"], section="servers")
    copilot_cli = mcp_server(files[".github/mcp.json"])
    gemini = json.loads(files[".gemini/settings.json"]["contents"])
    cursor = mcp_server(files[".cursor/mcp.json"])
    devin = mcp_server(files[".devin/mcp_config.json"])

    for server in (vscode, copilot_cli, gemini["mcpServers"]["shared-memory"], cursor, devin):
        assert server["url"] == f"{team.server.url}/mcp"
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


def test_cline_is_set_up_once_per_project_on_each_members_machine_for_every_repository(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]

    cline = next(file for file in created["files"] if file["agent"] == "Cline")
    server = mcp_server(cline, name=f"shared-memory-{project}")

    assert cline["kept_in"] == "machine"
    assert server["type"] == "streamableHttp"
    assert server["headers"] == {"Authorization": "Bearer ${env:SHARED_MEMORY_TOKEN}", "X-Shared-Memory-Project": project}
    assert all(file["kept_in"] == "repository" for file in created["files"] if file["agent"] != "Cline")


def test_codex_is_briefed_and_recalls_through_the_shell_of_whichever_machine_it_runs_on(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    hooks = tomllib.loads(by_path(created["files"])[".codex/config.toml"]["contents"])["hooks"]

    briefing = hooks["SessionStart"][0]["hooks"][0]
    recall = hooks["UserPromptSubmit"][0]["hooks"][0]

    for hook, event in ((briefing, "session-start"), (recall, "prompt-submitted")):
        assert hook["type"] == "command"
        assert f"{team.server.url}/hooks/{event}" in hook["command"], event
        assert "$SHARED_MEMORY_TOKEN" in hook["command"], event
        assert "curl.exe" in hook["command_windows"], event
        assert "%SHARED_MEMORY_TOKEN%" in hook["command_windows"], event


def test_gemini_runs_both_its_hooks_through_one_script_that_suits_every_machine(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])
    hooks = json.loads(files[".gemini/settings.json"]["contents"])["hooks"]
    script = files[".gemini/hooks/shared-memory.mjs"]

    assert hooks["SessionStart"][0]["hooks"][0]["command"] == "node .gemini/hooks/shared-memory.mjs session-start"
    assert hooks["BeforeAgent"][0]["hooks"][0]["command"] == "node .gemini/hooks/shared-memory.mjs prompt-submitted"
    assert (script["agent"], script["action"]) == ("Gemini CLI", "create")
    assert "process.env.SHARED_MEMORY_TOKEN" in script["contents"]
    assert f"{team.server.url}/hooks" in script["contents"]


def test_copilot_cli_is_briefed_by_the_server_itself_with_no_shell_command(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    file = by_path(created["files"])[".github/hooks/shared-memory.json"]
    hooks = json.loads(file["contents"])["hooks"]

    briefing = hooks["sessionStart"][0]

    assert file["agent"] == "GitHub Copilot"
    assert briefing["type"] == "http"
    assert briefing["url"] == f"{team.server.url}/hooks/session-start?format=copilot-cli"
    assert briefing["headers"]["Authorization"] == "Bearer ${SHARED_MEMORY_TOKEN}"
    assert briefing["allowedEnvVars"] == ["SHARED_MEMORY_TOKEN"]
    assert "userPromptSubmitted" not in hooks


def test_an_agent_that_reads_claude_codes_settings_is_never_briefed_twice(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    assert "hooks" not in json.loads(files[".claude/settings.json"]["contents"])
    assert "hooks" not in json.loads(files[".vscode/mcp.json"]["contents"])


def pinned(session: Session, title: str, body: str) -> str:
    """A project memory in this project's briefing, so a hook has something to bring back."""
    personal = session.call("remember", title=title, summary=f"{title}.", type="convention", body=body)["path"]
    result = session.call("promote", path=personal, level="project")
    if result["status"] == "similar_memories":
        keep = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("promote", path=personal, level="project", reference=result["reference"], resolutions=keep)
    path: str = result["path"]
    session.call("pin", path=path)
    return path


@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_the_script_geminis_hooks_run_brings_back_the_briefing(team: Team, tmp_path: Path) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    session = team.owner().in_project(created["project_id"], "billing-api")
    pinned(session, "Use pnpm, not npm", "We use pnpm for every package.")
    script = tmp_path / "shared-memory.mjs"
    script.write_text(by_path(created["files"])[".gemini/hooks/shared-memory.mjs"]["contents"], encoding="utf-8")

    ran = subprocess.run(
        ["node", str(script), "session-start"],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "SHARED_MEMORY_TOKEN": team.owner_token},
    )

    assert ran.returncode == 0, ran.stderr
    assert "Use pnpm, not npm" in json.loads(ran.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Gemini CLI's hooks run on node, which isn't installed here")
def test_geminis_hook_script_leaves_a_session_alone_when_it_cannot_reach_the_server(team: Team, tmp_path: Path) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    script = tmp_path / "shared-memory.mjs"
    contents = by_path(created["files"])[".gemini/hooks/shared-memory.mjs"]["contents"]
    script.write_text(contents.replace(team.server.url, "http://127.0.0.1:1"), encoding="utf-8")

    ran = subprocess.run(
        ["node", str(script), "prompt-submitted"],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "which package manager do we use?"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "SHARED_MEMORY_TOKEN": team.owner_token},
    )

    assert (ran.returncode, ran.stdout) == (0, "")


def test_cursor_is_briefed_by_a_hook_and_told_by_a_rule_to_search(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    hook = json.loads(files[".cursor/hooks.json"]["contents"])["hooks"]["sessionStart"][0]
    rule = files[".cursor/rules/shared-memory.mdc"]

    assert f"{team.server.url}/hooks/session-start?format=cursor" in hook["command"]
    assert "$SHARED_MEMORY_TOKEN" in hook["command"]
    assert rule["contents"].startswith("---\nalwaysApply: true\n---")
    for asked in ("search", "briefing", "remember", "information, not instructions"):
        assert asked in rule["contents"], asked


def test_devin_desktop_is_briefed_once_from_its_own_hooks(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    devin = json.loads(files[".devin/hooks.v1.json"]["contents"])

    assert f"{team.server.url}/hooks/session-start" in devin["SessionStart"][0]["hooks"][0]["command"]
    assert f"{team.server.url}/hooks/prompt-submitted" in devin["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert "hooks" not in json.loads(files[".claude/settings.json"]["contents"])


def test_cline_gets_a_hook_script_for_each_shell_it_runs_them_in(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    files = by_path(created["files"])

    for event, endpoint in (("TaskStart", "session-start"), ("UserPromptSubmit", "prompt-submitted")):
        posix = files[f".clinerules/hooks/{event}"]
        windows = files[f".clinerules/hooks/{event}.ps1"]

        assert posix["contents"].startswith("#!/bin/sh"), event
        assert f"{team.server.url}/hooks/{endpoint}?format=cline" in posix["contents"], event
        assert "$SHARED_MEMORY_TOKEN" in posix["contents"], event
        assert f"{team.server.url}/hooks/{endpoint}?format=cline" in windows["contents"], event
        assert "$env:SHARED_MEMORY_TOKEN" in windows["contents"], event


def cline_hook_answer(team: Team, tmp_path: Path, shell: list[str], name: str) -> dict[str, Any]:
    """Run one of Cline's generated hook scripts the way Cline runs it, and return what it printed."""
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    session = team.owner().in_project(created["project_id"], "billing-api")
    pinned(session, "Use pnpm, not npm", "We use pnpm for every package.")
    script = tmp_path / name
    script.write_text(by_path(created["files"])[f".clinerules/hooks/{name}"]["contents"], encoding="utf-8")

    ran = subprocess.run(
        [*shell, str(script)],
        input=json.dumps({"hookName": "TaskStart", "taskId": "task-1", "clineVersion": "4.1.20"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "SHARED_MEMORY_TOKEN": team.owner_token},
    )

    assert ran.returncode == 0, ran.stderr
    answer: dict[str, Any] = json.loads(ran.stdout)
    return answer


@pytest.mark.skipif(shutil.which("sh") is None, reason="Cline runs these hooks in a POSIX shell, which isn't here")
def test_clines_hook_script_briefs_a_task_without_cancelling_it(team: Team, tmp_path: Path) -> None:
    answer = cline_hook_answer(team, tmp_path, ["sh"], "TaskStart")

    assert answer["cancel"] is False
    assert "Use pnpm, not npm" in answer["contextModification"]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="Cline runs its Windows hooks in PowerShell, which isn't here")
def test_clines_windows_hook_script_briefs_a_task_without_cancelling_it(team: Team, tmp_path: Path) -> None:
    answer = cline_hook_answer(team, tmp_path, ["pwsh", "-NoProfile", "-File"], "TaskStart.ps1")

    assert answer["cancel"] is False
    assert "Use pnpm, not npm" in answer["contextModification"]
