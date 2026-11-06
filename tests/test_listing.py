"""What the marketplaces read: `server.json` for the MCP Registry, and the two Claude Code plugin manifests (#452)."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "tests" / "schemas" / "mcp-registry-server.schema.json"
FSL = "FSL-1.1-ALv2"
REPOSITORY = "https://github.com/madhav037/shared-memory"


def load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_server_json_follows_the_mcp_registry_schema() -> None:
    server = load(ROOT / "server.json")
    schema = load(SCHEMA)

    jsonschema.validate(server, schema)

    assert server["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert server["name"] == "io.github.madhav037/shared-memory"
    assert server["repository"] == {"url": REPOSITORY, "source": "github"}
    assert server["websiteUrl"] == REPOSITORY


def test_server_json_describes_a_remote_server_taking_the_personal_token_in_a_header() -> None:
    server = load(ROOT / "server.json")

    (remote,) = server["remotes"]
    authorization = next(header for header in remote["headers"] if header["name"] == "Authorization")

    assert remote["type"] == "streamable-http"
    assert remote["url"] == "https://{server_host}/mcp"
    assert remote["variables"]["server_host"]["isRequired"] is True
    assert authorization["value"] == "Bearer {personal_token}"
    assert authorization["isSecret"] is True
    assert "packages" not in server


def test_the_plugin_manifests_parse_and_point_at_the_repository() -> None:
    marketplace = load(ROOT / ".claude-plugin" / "marketplace.json")
    manifest = load(ROOT / "plugin" / ".claude-plugin" / "plugin.json")
    (entry,) = marketplace["plugins"]

    assert marketplace["owner"]["name"]
    assert entry["name"] == manifest["name"] == "shared-memory"
    assert entry["source"] == "./plugin"
    assert manifest["homepage"] == REPOSITORY
    assert manifest["repository"] == REPOSITORY
    assert manifest["license"] == FSL
    assert manifest["version"]
    assert manifest["description"]
    # plugin.json wins over the marketplace entry for a version, and Claude Code warns when both set one.
    assert "version" not in entry
