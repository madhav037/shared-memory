"""The console's JSON API, which the console asks before anyone signs in."""

from __future__ import annotations

import json
from typing import Any

import httpx

from tests.support import REPO_ROOT, HostedConsole, RunningServer, Session, Company


def get(server: RunningServer, path: str) -> dict[str, Any]:
    response = httpx.get(f"{server.url}{path}", timeout=30)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_console_is_told_that_nobody_is_signed_in(server: RunningServer) -> None:
    status = get(server, "/api/status")

    assert status == {
        "signed_in": False,
        "github_sign_in": False,
        "hosted": False,
        "member": None,
        "server_url": server.url,
        "platform_url": None,
    }


def test_the_console_is_told_the_platforms_address_so_its_links_to_the_landing_page_reach_it(
    hosted_console: HostedConsole,
) -> None:
    status = get(hosted_console.server, "/api/status")

    assert status["platform_url"] == hosted_console.platform.url.rstrip("/")


def test_the_console_is_told_whether_the_server_is_hosted_so_it_says_what_setting_up_sign_in_takes(
    hosted_console: HostedConsole, server: RunningServer
) -> None:
    assert get(hosted_console.server, "/api/status")["hosted"] is True
    assert get(server, "/api/status")["hosted"] is False


def test_the_console_is_told_the_address_agents_reach_the_server_at_the_one_the_repositorys_files_name(
    company: Company,
) -> None:
    owner = company.owner()
    project = owner.call("create_project", name="Billing")
    named = {file["path"]: file["contents"] for file in project["files"]}

    status = get(company.server, "/api/status")

    assert status["server_url"] == company.server.url
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
        "hosted",
        "member",
        "server_url",
        "platform_url",
    }
    assert "SignedInMember" in document["components"]["schemas"]
    assert document["paths"]["/api/sign-in/github"]["get"]["responses"].keys() == {"302"}


def test_the_console_api_leaves_the_memory_tools_and_the_hooks_alone(company: Company) -> None:
    owner = company.owner()
    project = owner.call("create_project", name="Billing")["project_id"]
    session = Session(company.server, company.owner_token, project, "billing-api")

    get(company.server, "/api/status")

    assert session.call("tree")["folders"] == []
    assert session.end() == {}


def test_the_server_prints_its_api_description_for_the_consoles_build(server: RunningServer) -> None:
    printed = json.loads(server.run_cli("openapi"))

    assert printed == get(server, "/api/openapi.json")


def test_the_consoles_copy_of_the_api_description_is_current(server: RunningServer) -> None:
    committed = json.loads((REPO_ROOT / "console" / "openapi.json").read_text(encoding="utf-8"))

    assert committed == get(server, "/api/openapi.json"), "run: uv run shared-memory openapi > console/openapi.json"
