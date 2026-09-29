"""Behind a CDN, nothing the server answers for one member may be kept and shown to another."""

from __future__ import annotations

import httpx

from tests.support import Console, ConsoleClient, Session, Team, signed_in_owner

NO_STORE = "no-store"


def test_the_memory_tools_are_never_kept_by_a_cache(owner: Session) -> None:
    response = httpx.post(
        f"{owner.server.url}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "cdn", "version": "1"}},
        },
        headers={**owner.headers(), "Accept": "application/json, text/event-stream"},
        timeout=30,
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE


def test_a_hook_answer_is_never_kept_by_a_cache(owner: Session) -> None:
    response = httpx.post(
        f"{owner.server.url}/hooks/session-start",
        json={"session_id": "cdn", "cwd": "/work/app", "hook_event_name": "SessionStart", "source": "startup"},
        headers=owner.headers(),
        timeout=30,
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE


def test_a_refused_request_is_never_kept_by_a_cache(team: Team) -> None:
    stranger = Session(team.server, "not-a-token")

    hook = httpx.post(f"{stranger.server.url}/hooks/prompt-submitted", json={}, headers=stranger.headers(), timeout=30)
    tool = httpx.post(f"{stranger.server.url}/mcp", json={}, headers=stranger.headers(), timeout=30)

    assert hook.headers["cache-control"] == NO_STORE
    assert tool.headers["cache-control"] == NO_STORE


def test_the_console_api_is_never_kept_by_a_cache(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-cdn", 7101)

    for path in ("/api/status", "/api/openapi.json", "/api/no-such-thing"):
        assert signed_out.get(path).headers["cache-control"] == NO_STORE, path
    assert signed_out.sign_out().headers["cache-control"] == NO_STORE


def test_what_is_not_the_api_the_tools_or_the_hooks_is_left_to_the_cache(console: Console) -> None:
    response = httpx.get(f"{console.server.url}/robots.txt", timeout=30)

    assert "cache-control" not in response.headers
