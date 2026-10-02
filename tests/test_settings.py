"""The settings a deployment sets, and the host guard only a deployment turns on."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import RunningServer, TestClock


def test_an_empty_environment_gives_the_documented_defaults() -> None:
    settings = Settings.from_env({})

    assert settings.database_url == "postgresql://postgres:postgres@localhost:5433/shared_memory"
    assert settings.memory_root == Path("data/memory")
    assert settings.model_cache == Path(".cache/fastembed")
    assert settings.allowed_hosts == ()
    assert settings.plugin_marketplace == "madhav037/shared-memory"
    assert settings.github_sign_in_url == "https://github.com"
    assert settings.github_api_url == "https://api.github.com"
    assert settings.console_url == ""
    assert settings.github_sign_in is False


def test_every_setting_from_env_reads_is_read() -> None:
    settings = Settings.from_env(
        {
            "SHARED_MEMORY_DATABASE_URL": "postgresql://elsewhere/db",
            "SHARED_MEMORY_ROOT": "/srv/memory",
            "SHARED_MEMORY_MODEL_CACHE": "/srv/cache",
            "SHARED_MEMORY_ALLOWED_HOSTS": "memory.example.com",
            "SHARED_MEMORY_PLUGIN_MARKETPLACE": "someone/else",
            "SHARED_MEMORY_GITHUB_CLIENT_ID": "an-id",
            "SHARED_MEMORY_GITHUB_CLIENT_SECRET": "a-secret",
            "SHARED_MEMORY_GITHUB_SIGN_IN_URL": "https://github.example.com",
            "SHARED_MEMORY_GITHUB_API_URL": "https://api.github.example.com",
            "SHARED_MEMORY_CONSOLE_URL": "https://memory.example.com",
        }
    )

    assert settings.database_url == "postgresql://elsewhere/db"
    assert settings.memory_root == Path("/srv/memory")
    assert settings.model_cache == Path("/srv/cache")
    assert settings.allowed_hosts == ("memory.example.com",)
    assert settings.plugin_marketplace == "someone/else"
    assert settings.github_client_id == "an-id"
    assert settings.github_client_secret == "a-secret"
    assert settings.github_sign_in_url == "https://github.example.com"
    assert settings.github_api_url == "https://api.github.example.com"
    assert settings.console_url == "https://memory.example.com"
    assert settings.github_sign_in is True


def test_a_server_can_be_told_more_than_one_allowed_host() -> None:
    settings = Settings.from_env({"SHARED_MEMORY_ALLOWED_HOSTS": " memory.example.com , 10.0.0.4 ,"})

    assert settings.allowed_hosts == ("memory.example.com", "10.0.0.4")


def test_signing_in_needs_both_halves_of_the_github_app() -> None:
    assert Settings.from_env({"SHARED_MEMORY_GITHUB_CLIENT_ID": "an-id"}).github_sign_in is False
    assert Settings.from_env({"SHARED_MEMORY_GITHUB_CLIENT_SECRET": "a-secret"}).github_sign_in is False


def test_the_collision_threshold_reads_its_environment_variable() -> None:
    assert Settings.from_env({}).collision_threshold == 0.75
    assert Settings.from_env({"SHARED_MEMORY_COLLISION_THRESHOLD": "0.9"}).collision_threshold == 0.9


class StubEmbedder:
    """Stands in for the real model: no request in this module gets far enough to need an embedding."""

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def query(self, text: str) -> list[float]:
        return [0.0]

    def tokens(self, words: list[str]) -> list[int]:
        return [1 for _ in words]


@pytest.fixture(scope="module")
def guarded(server: RunningServer) -> Iterator[RunningServer]:
    """The server as a deployment builds it: allowed_hosts set, so the host guard is installed."""
    settings = Settings(
        database_url=server.settings.database_url,
        memory_root=server.settings.memory_root,
        model_cache=server.settings.model_cache,
        allowed_hosts=("memory.example.com",),
    )
    with start_blocking_portal() as portal:
        running = RunningServer(build_app(settings, embedder=StubEmbedder()), settings, TestClock(), portal)
        try:
            yield running
        finally:
            running.stop()


MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def asking_as(guarded: RunningServer, host: str) -> httpx.Response:
    """A well-formed MCP request, claiming to have been sent to `host`."""
    return httpx.post(f"{guarded.url}/mcp", headers={**MCP_HEADERS, "Host": host}, json=LIST_TOOLS)


def test_a_request_for_a_host_the_server_was_not_told_about_is_refused(guarded: RunningServer) -> None:
    refused = asking_as(guarded, "memory.attacker.example")

    assert refused.status_code == 421, refused.text
    assert "Host" in refused.text


def test_a_request_for_an_allowed_host_is_answered(guarded: RunningServer) -> None:
    answered = asking_as(guarded, "memory.example.com")

    assert answered.status_code == 200, answered.text
    assert answered.json()["result"]["tools"]
