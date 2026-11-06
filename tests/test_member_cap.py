"""The member cap: a server refuses to add a member past it, and a removed member frees a place (spec #416)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import LazyEmbedder
from tests.support import (
    REPO_ROOT,
    Console,
    ConsoleClient,
    FakeGitHub,
    RunningServer,
    TestClock,
    add,
    fresh_database,
    signed_in_owner,
)


@pytest.fixture(scope="module")
def console(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Console]:
    with start_blocking_portal() as portal:
        memory = tmp_path_factory.mktemp("member-cap-memory")
        sign_in = FakeGitHub(portal, Settings("", Path(memory), Path(memory)))
        clock = TestClock()
        settings = Settings(
            database_url=fresh_database("shared_memory_member_cap"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=sign_in.url,
            github_api_url=sign_in.url,
            rate_limit_on=False,
        )
        server = RunningServer(
            build_app(settings, clock=clock, embedder=LazyEmbedder(settings.model_cache)), settings, clock, portal
        )
        try:
            yield Console(server, sign_in, clock)
        finally:
            server.stop()
            sign_in.stop()


def capped_at_places_left(console: Console, places: int) -> None:
    """Set the cap so that this many more members fit on the server, whoever is already on it."""
    identity = console.server.app.state.identity
    identity.member_cap = lambda: identity.members_in_use() + places


def team_page(client: ConsoleClient) -> dict[str, Any]:
    response = client.get("/api/members")
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()
    return page


def test_a_server_with_no_cap_adds_members_and_says_there_is_none(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-cap-none", 701)
    console.server.app.state.identity.member_cap = lambda: None

    add(client, "emp-2", "Dana Dev")

    page = team_page(client)
    assert page["member_cap"] is None
    assert page["members_used"] >= 2


def test_adding_a_member_past_the_cap_is_refused_over_mcp(console: Console) -> None:
    client = console.client()
    owner = signed_in_owner(console, client, "olive-cap-mcp", 702)
    capped_at_places_left(console, 1)

    owner.call("add_member", member_id="emp-2", name="Dana Dev")
    refusal = owner.refusal("add_member", member_id="emp-3", name="Eve Eng")

    assert "member cap" in refusal
    assert "SHARED_MEMORY_MEMBER_CAP" in refusal


def test_the_console_refuses_a_member_past_the_cap_and_shows_places_used(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-cap-console", 703)
    capped_at_places_left(console, 1)
    add(client, "emp-2", "Dana Dev")

    refused = client.post_json("/api/members", {"member_id": "emp-3", "name": "Eve Eng", "github": None})

    assert refused.status_code == 403
    assert "member cap" in refused.json()["message"]
    page = team_page(client)
    assert page["member_cap"] == page["members_used"]


def test_removing_a_member_frees_a_place(console: Console) -> None:
    client = console.client()
    owner = signed_in_owner(console, client, "olive-cap-free", 704)
    capped_at_places_left(console, 1)
    add(client, "emp-2", "Dana Dev")
    assert "member cap" in owner.refusal("add_member", member_id="emp-3", name="Eve Eng")

    owner.call("remove_member", member_id="emp-2")

    assert owner.call("add_member", member_id="emp-3", name="Eve Eng")["member_id"] == "emp-3"


def test_the_cap_is_read_from_the_environment() -> None:
    assert Settings.from_env({"SHARED_MEMORY_MEMBER_CAP": "10"}).member_cap == 10
    assert Settings.from_env({"SHARED_MEMORY_MEMBER_CAP": " "}).member_cap is None
    assert Settings.from_env({}).member_cap is None
