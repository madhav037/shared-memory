"""The rate limit: one personal token's calls are counted, and one over its limit is told to slow down (spec #405).

Every test drives the server over HTTP, as a coding agent does. The server here has a tiny limit and a clock the tests
move by hand, so nothing waits. The shared fixtures switch the limit off (their clock never moves, so a bucket would
never refill), which is why this module builds its own servers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import LazyEmbedder
from shared_memory.ratelimit import burst_of
from tests.support import REPO_ROOT, RunningServer, TestClock, fresh_database, new_team

PER_MINUTE = 80
BURST = burst_of(PER_MINUTE)

MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture(scope="module")
def limited(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = Settings(
        database_url=fresh_database("shared_memory_rate_limit"),
        memory_root=tmp_path_factory.mktemp("rate-limit-memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
        rate_limit_token_per_minute=PER_MINUTE,
    )
    clock = TestClock()
    with start_blocking_portal() as portal:
        running = RunningServer(
            build_app(settings, clock=clock, embedder=LazyEmbedder(settings.model_cache)), settings, clock, portal
        )
        try:
            yield running
        finally:
            running.stop()


@pytest.fixture(scope="module")
def another_worker(limited: RunningServer) -> Iterator[RunningServer]:
    """A second server instance on the same database: to Postgres, a second worker (ADR-0013)."""
    app = build_app(limited.settings, clock=limited.clock, embedder=LazyEmbedder(limited.settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, limited.settings, limited.clock, portal)
        try:
            yield running
        finally:
            running.stop()


def a_token(server: RunningServer) -> str:
    """A personal token no call has used yet."""
    server.clock.now = TestClock().now
    return new_team(server).owner_token


def prompt(server: RunningServer, token: str) -> httpx.Response:
    """One prompt hook call. It carries no project, so the server answers it emptily, but it counts as a call."""
    return httpx.post(
        f"{server.url}/hooks/prompt-submitted",
        json={"session_id": "s", "prompt": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )


def tool_call(server: RunningServer, token: str, identifier: int = 7) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": identifier, "method": "tools/call", "params": {"name": "tree", "arguments": {}}}
    return httpx.post(f"{server.url}/mcp", json=body, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"})


def used_up(server: RunningServer, token: str) -> httpx.Response:
    """Call until the token is limited; return the refusal. The calls before it were all answered."""
    for allowed in range(BURST + 5):
        response = prompt(server, token)
        if response.status_code == 429:
            assert allowed == BURST, f"limited after {allowed} calls, not the burst of {BURST}"
            return response
        assert response.status_code == 200, response.text
    raise AssertionError("the token was never limited")


def wait_of(response: httpx.Response) -> int:
    header = response.headers["Retry-After"]
    assert header.isdigit() and int(header) >= 1, header
    return int(header)


def test_a_personal_token_may_burst_and_is_then_told_how_long_to_wait(limited: RunningServer) -> None:
    refused = used_up(limited, a_token(limited))

    assert refused.status_code == 429
    assert wait_of(refused) >= 1
    assert refused.headers["Cache-Control"] == "no-store"


def test_a_tool_call_over_the_limit_gets_a_tool_error_naming_the_wait(limited: RunningServer) -> None:
    token = a_token(limited)
    wait = wait_of(used_up(limited, token))

    refused = tool_call(limited, token, identifier=41)

    assert refused.status_code == 429
    assert wait_of(refused) == wait
    answer: dict[str, Any] = refused.json()
    assert answer["id"] == 41
    assert answer["result"]["isError"] is True
    assert f"try again in {wait} second" in answer["result"]["content"][0]["text"]


def test_a_prompt_hook_over_the_limit_adds_nothing(limited: RunningServer) -> None:
    token = a_token(limited)
    used_up(limited, token)

    refused = prompt(limited, token)

    assert refused.status_code == 429
    assert refused.json() == {}


def test_a_before_edit_hook_over_the_limit_is_answered_as_when_the_server_is_unreachable(
    limited: RunningServer,
) -> None:
    token = a_token(limited)
    used_up(limited, token)

    refused = httpx.post(
        f"{limited.url}/hooks/before-edit",
        json={"session_id": "s", "tool_name": "Edit", "tool_input": {"file_path": "/work/app/a.py"}},
        headers={"Authorization": f"Bearer {token}"},
    )

    # The plugin's hook calls curl with --fail, so a 429 is the same failure to it as no answer; the body blocks nothing.
    assert refused.status_code == 429
    assert refused.json() == {}
    assert "deny" not in refused.text


def test_calls_are_allowed_again_once_the_wait_has_passed(limited: RunningServer) -> None:
    token = a_token(limited)
    wait = wait_of(used_up(limited, token))

    limited.clock.advance(seconds=wait - 1)
    assert prompt(limited, token).status_code == 429  # a second short of the wait

    limited.clock.advance(seconds=1)
    assert prompt(limited, token).status_code == 200
    assert prompt(limited, token).status_code == 429  # the wait bought one call, not a whole burst


def test_one_personal_token_being_limited_never_limits_another(limited: RunningServer) -> None:
    busy, quiet = a_token(limited), new_team(limited).owner_token
    used_up(limited, busy)

    assert prompt(limited, quiet).status_code == 200


def test_ordinary_use_stays_under_the_limit(limited: RunningServer) -> None:
    owner = new_team(limited).owner()

    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")

    assert in_project.call("tree")["folders"] is not None
    assert in_project.start() is not None
    assert prompt(limited, owner.token or "").status_code == 200


def test_the_health_check_is_never_limited(limited: RunningServer) -> None:
    token = a_token(limited)
    used_up(limited, token)

    assert httpx.get(f"{limited.url}/health", headers={"Authorization": f"Bearer {token}"}).status_code != 429


def test_two_workers_share_one_allowance(limited: RunningServer, another_worker: RunningServer) -> None:
    token = a_token(limited)
    workers = [limited, another_worker]

    answered = 0
    for call in range(BURST * 2):
        if prompt(workers[call % 2], token).status_code == 200:
            answered += 1

    assert answered == BURST


def test_a_fault_in_the_counter_never_stops_a_call(limited: RunningServer, monkeypatch: pytest.MonkeyPatch) -> None:
    token = a_token(limited)

    def broken(key: str, per_minute: int) -> int | None:
        raise RuntimeError("the counter is down")

    monkeypatch.setattr(limited.app.state.rate_limits, "_take", broken)

    assert all(prompt(limited, token).status_code == 200 for _ in range(BURST * 2))
    assert tool_call(limited, token).status_code != 429


def test_a_server_with_the_limit_switched_off_counts_nothing(limited: RunningServer) -> None:
    token = a_token(limited)
    off = dataclasses.replace(limited.settings, rate_limit_on=False)
    with start_blocking_portal() as portal:
        app = build_app(off, clock=limited.clock, embedder=LazyEmbedder(off.model_cache))
        running = RunningServer(app, off, limited.clock, portal)
        try:
            assert all(prompt(running, token).status_code == 200 for _ in range(BURST * 2))
        finally:
            running.stop()


def test_the_defaults_are_120_calls_a_minute_with_a_burst_of_30() -> None:
    settings = Settings.from_env({})

    assert settings.rate_limit_on is True
    assert settings.rate_limit_token_per_minute == 120
    assert burst_of(settings.rate_limit_token_per_minute) == 30


def test_the_limit_reads_its_environment_variables() -> None:
    settings = Settings.from_env(
        {"SHARED_MEMORY_RATE_LIMIT": "off", "SHARED_MEMORY_RATE_LIMIT_TOKEN_PER_MINUTE": "240"}
    )

    assert settings.rate_limit_on is False
    assert settings.rate_limit_token_per_minute == 240

