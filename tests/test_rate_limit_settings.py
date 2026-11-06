"""Admins see and change the rate limits from the console, and a limited personal token is audited (spec #405).

The shared console server has the limit switched off (its clock never moves), so each test that turns it on sets it
back before it ends, and the module's first test reads the limits as the environment set them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from shared_memory.ratelimit import burst_of
from tests.support import Console, ConsoleClient, add, signed_in_owner

DEFAULTS = {"on": False, "token_per_minute": 120, "console_per_minute": 300, "address_per_minute": 30}


def limits(client: ConsoleClient) -> dict[str, Any]:
    response = client.get("/api/rate-limits")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def change(client: ConsoleClient, **changed: Any) -> httpx.Response:
    wanted = {**DEFAULTS, **changed}
    return client.post_json("/api/rate-limits", wanted)


@contextmanager
def set_limits(client: ConsoleClient, **changed: Any) -> Iterator[None]:
    """The limits as set for one test, and the environment's numbers again afterwards."""
    assert change(client, **changed).status_code == 200
    try:
        yield
    finally:
        assert change(client).status_code == 200


def audit(client: ConsoleClient, kind: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/audit?kind={kind}")
    assert response.status_code == 200, response.text
    events: list[dict[str, Any]] = response.json()["events"]
    return events


def prompt(console: Console, token: str) -> int:
    return httpx.post(
        f"{console.server.url}/hooks/prompt-submitted",
        json={"session_id": "s", "prompt": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    ).status_code


def test_every_member_sees_the_limits_in_force_and_only_admins_may_change_them(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-limits-one", 701)
    add(signed_out, "emp-2", "Dana Dev", "dana-limits-one")
    dana = console.client()
    console.github.as_(702, "dana-limits-one")
    dana.sign_in()

    assert limits(signed_out) == {**DEFAULTS, "you_may_change": True}
    assert limits(dana) == {**DEFAULTS, "you_may_change": False}
    refused = change(dana, token_per_minute=1000)
    assert refused.status_code == 403
    assert "owner and its admins" in refused.json()["message"]
    assert limits(signed_out)["token_per_minute"] == 120
    dana.close()


def test_an_admin_changes_the_limits_and_the_audit_log_says_who(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-limits-two", 703)

    with set_limits(signed_out, token_per_minute=240, console_per_minute=600, address_per_minute=60):
        assert limits(signed_out) == {
            "on": False,
            "token_per_minute": 240,
            "console_per_minute": 600,
            "address_per_minute": 60,
            "you_may_change": True,
        }
        changed = audit(signed_out, "rate_limits_changed")[0]
        assert changed["actor"] == "Olive Owner"
        assert changed["detail"]["now"]["token_per_minute"] == 240
        assert changed["detail"]["before"]["token_per_minute"] == 120


def test_a_limit_outside_what_makes_sense_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-limits-three", 704)

    assert change(signed_out, token_per_minute=0).status_code == 422
    assert change(signed_out, address_per_minute=10_000_000).status_code == 422
    assert limits(signed_out)["token_per_minute"] == 120


def test_the_limits_can_be_switched_off_and_on_from_the_console(console: Console, signed_out: ConsoleClient) -> None:
    agent = signed_in_owner(console, signed_out, "olive-limits-four", 705)
    token = agent.token or ""
    burst = burst_of(8)

    with set_limits(signed_out, on=True, token_per_minute=8):
        assert [prompt(console, token) for _ in range(burst + 1)] == [200] * burst + [429]
        assert change(signed_out, on=False, token_per_minute=8).status_code == 200
        assert [prompt(console, token) for _ in range(burst + 3)] == [200] * (burst + 3)


def test_the_first_time_in_an_hour_a_personal_token_is_limited_the_audit_log_names_its_member(
    console: Console, signed_out: ConsoleClient
) -> None:
    agent = signed_in_owner(console, signed_out, "olive-limits-five", 706)
    token = agent.token or ""
    burst = burst_of(8)

    with set_limits(signed_out, on=True, token_per_minute=8):
        for _ in range(burst + 5):
            prompt(console, token)
        limited = audit(signed_out, "token_limited")
        assert [(event["actor"], event["target"]) for event in limited] == [("Olive Owner", "E1001")]
        assert limited[0]["detail"] == {"per_minute": 8}

        # An hour later the token is limited again, and that is noted again.
        console.clock.advance(hours=1, seconds=5)
        for _ in range(burst + 5):
            prompt(console, token)
        assert len(audit(signed_out, "token_limited")) == 2


def test_only_signed_in_members_read_the_limits(console: Console, signed_out: ConsoleClient) -> None:
    assert signed_out.get("/api/rate-limits").status_code == 401
    assert change(signed_out).status_code == 401
