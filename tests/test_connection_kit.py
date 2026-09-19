"""Connecting a repository: the files each coding agent commits so its sessions reach the project."""

from __future__ import annotations

import json
import tomllib
from typing import Any

from tests.support import REPO_ROOT, Team


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


def test_cline_is_set_up_once_per_project_on_each_members_machine(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    project = created["project_id"]

    cline = next(file for file in created["files"] if file["agent"] == "Cline")
    server = mcp_server(cline, name=f"shared-memory-{project}")

    assert cline["scope"] == "machine"
    assert server["type"] == "streamableHttp"
    assert server["headers"]["Authorization"] == "Bearer ${env:SHARED_MEMORY_TOKEN}"
    assert server["headers"]["X-Shared-Memory-Project"] == project
    assert all(file["scope"] == "repository" for file in created["files"] if file["agent"] != "Cline")
