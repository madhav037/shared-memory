from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support import Session, Team

REPO = Path(__file__).resolve().parent.parent


def test_create_project_gives_settings_that_install_the_plugin_and_connect_the_repository(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-web")

    settings = created["settings"]
    marketplace = team.server.settings.plugin_marketplace

    assert settings["extraKnownMarketplaces"] == {"shared-memory": {"source": {"source": "github", "repo": marketplace}}}
    assert settings["enabledPlugins"] == {"shared-memory@shared-memory": True}
    assert settings["env"] == {"SHARED_MEMORY_PROJECT": created["project_id"], "SHARED_MEMORY_REPOSITORY": "billing-web"}


def test_the_generated_plugin_name_matches_the_marketplace_and_plugin_in_this_repository() -> None:
    marketplace = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    entry = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "shared-memory")
    manifest = json.loads((REPO / entry["source"] / ".claude-plugin" / "plugin.json").read_text())

    assert marketplace["name"] == "shared-memory"
    assert manifest["name"] == "shared-memory"
    assert manifest["userConfig"]["api_token"]["sensitive"] is True
    assert manifest["userConfig"]["server_url"]["sensitive"] is False


def test_several_repositories_share_one_projects_memory(team: Team) -> None:
    project = team.owner().call("create_project", name="Billing", repository="billing-web")["project_id"]
    web = team.owner().in_project(project, "billing-web")
    api = team.owner().in_project(project, "billing-api")
    personal = web.call(
        "remember", title="Money amounts", summary="Money is integer cents.", type="convention", body="Amounts are integer cents."
    )["path"]
    promoted = web.call("promote", path=personal, level="project")["path"]

    results = api.call("search", query="how are money amounts stored")["results"]

    assert results[0]["path"] == promoted


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search", {"query": "anything"}),
        ("tree", {}),
        ("promote", {"path": "projects/x/people/owner-1/conventions/a.md", "level": "project"}),
    ],
)
def test_memory_tools_in_a_repository_without_a_project_explain_why(team: Team, tool: str, arguments: dict[str, object]) -> None:
    unconnected = Session(team.server, team.owner_token)

    assert "isn't connected to a project" in unconnected.refusal(tool, **arguments)
