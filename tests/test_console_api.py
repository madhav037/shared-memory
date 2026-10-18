"""The console's JSON API, which the console asks before anyone signs in."""

from __future__ import annotations

import json
from typing import Any

import httpx

from tests.support import REPO_ROOT, RunningServer, Session, Team


def get(server: RunningServer, path: str) -> dict[str, Any]:
    response = httpx.get(f"{server.url}{path}", timeout=30)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_console_is_told_that_nobody_is_signed_in(server: RunningServer) -> None:
    status = get(server, "/api/status")

    assert status == {"signed_in": False, "github_sign_in": False, "member": None, "server_url": server.url}


def test_the_console_is_told_the_address_agents_reach_the_server_at_the_one_the_repositorys_files_name(
    team: Team,
) -> None:
    owner = team.owner()
    project = owner.call("create_project", name="Billing")
    named = {file["path"]: file["contents"] for file in project["files"]}

    status = get(team.server, "/api/status")

    assert status["server_url"] == team.server.url
    assert f"{status['server_url']}/mcp" in named[".codex/config.toml"]


def test_the_api_describes_itself_so_the_console_can_generate_its_types(server: RunningServer) -> None:
    document = get(server, "/api/openapi.json")

    assert document["openapi"].startswith("3.1")
    assert "/api/status" in document["paths"]
    schema = document["paths"]["/api/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/Status"}
    assert document["components"]["schemas"]["Status"]["properties"].keys() == {
        "signed_in",
        "github_sign_in",
        "member",
        "server_url",
    }
    assert "SignedInMember" in document["components"]["schemas"]
    assert document["paths"]["/api/sign-in/github"]["get"]["responses"].keys() == {"302"}


def test_the_console_api_leaves_the_memory_tools_and_the_hooks_alone(team: Team) -> None:
    owner = team.owner()
    project = owner.call("create_project", name="Billing")["project_id"]
    session = Session(team.server, team.owner_token, project, "billing-api")

    get(team.server, "/api/status")

    assert session.call("tree")["folders"] == []
    assert session.end() == {}


def test_the_server_prints_its_api_description_for_the_consoles_build(server: RunningServer) -> None:
    printed = json.loads(server.run_cli("openapi"))

    assert printed == get(server, "/api/openapi.json")


def test_the_consoles_copy_of_the_api_description_is_current(server: RunningServer) -> None:
    committed = json.loads((REPO_ROOT / "console" / "openapi.json").read_text(encoding="utf-8"))

    assert committed == get(server, "/api/openapi.json"), "run: uv run shared-memory openapi > console/openapi.json"
