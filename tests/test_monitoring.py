"""Server errors reach Sentry with memory text, tokens and member identifiers removed (#436, spec #407)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from shared_memory.config import Settings
from shared_memory.monitoring import scrub, scrub_breadcrumb, start_reporting

DSN = "https://publickey@o0.ingest.sentry.io/0"
PRIVATE = (
    "Quokka retention is thirty days",  # a memory body
    "smp_secret_personal_token",
    "session=cookie-value",
    "dana-the-member",
    "dana-github-login",
    "q=quokka+retention",
    "ignore previous instructions",
)


def settings(dsn: str = "") -> Settings:
    return Settings(database_url="postgresql://unused", memory_root=Path("memory"), model_cache=Path("cache"), sentry_dsn=dsn)


def real_shaped_event() -> dict[str, Any]:
    """An event as the Starlette integration builds it, with every kind of private data in it."""
    return {
        "event_id": "0" * 32,
        "level": "error",
        "transaction": "/console/api/members/{member_id}",
        "server_name": "shared-memory-1",
        "release": "0.1.1",
        "message": "Quokka retention is thirty days",
        "logentry": {"message": "saving %s", "params": ["Quokka retention is thirty days"]},
        "user": {"id": "dana-the-member", "username": "dana-github-login", "ip_address": "203.0.113.9"},
        "tags": {"member": "dana-the-member"},
        "extra": {"body": "Quokka retention is thirty days", "github": "dana-github-login"},
        "modules": {"starlette": "1.6.0"},
        "request": {
            "method": "POST",
            "url": "https://memory.example.com/console/api/members/dana-the-member?q=quokka+retention",
            "query_string": "q=quokka+retention",
            "data": {"body": "Quokka retention is thirty days"},
            "cookies": {"session": "cookie-value"},
            "headers": {
                "Authorization": "Bearer smp_secret_personal_token",
                "Cookie": "session=cookie-value",
                "X-Shared-Memory-Token": "smp_secret_personal_token",
            },
            "env": {"REMOTE_ADDR": "203.0.113.9"},
        },
        "contexts": {
            "runtime": {"name": "CPython", "version": "3.12.12"},
            "response": {"status_code": 500},
            "trace": {"trace_id": "1" * 32, "span_id": "2" * 16},
            "member": {"id": "dana-the-member"},
        },
        "breadcrumbs": {
            "values": [
                {"type": "default", "category": "query", "message": "SELECT", "data": {"body": PRIVATE[0]}},
                {"type": "default", "category": "auth", "message": "dana-the-member signed in", "level": "info"},
            ]
        },
        "exception": {
            "values": [
                {
                    "type": "KeyError",
                    "value": "'Quokka retention is thirty days' for dana-the-member",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "shared_memory/service.py",
                                "function": "remember",
                                "lineno": 160,
                                "vars": {"body": "Quokka retention is thirty days", "token": "smp_secret_personal_token"},
                            }
                        ]
                    },
                }
            ]
        },
    }


def test_no_private_data_survives_the_scrubber() -> None:
    sent = json.dumps(scrub(real_shaped_event()))

    for secret in PRIVATE:
        assert secret not in sent, secret


def test_the_scrubber_keeps_what_fixing_the_bug_needs() -> None:
    sent = scrub(real_shaped_event())

    assert sent["exception"]["values"][0]["type"] == "KeyError"
    frame = sent["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert (frame["filename"], frame["function"], frame["lineno"]) == ("shared_memory/service.py", "remember", 160)
    assert sent["request"] == {"method": "POST"}
    assert sent["transaction"] == "/console/api/members/{member_id}"
    assert sent["release"] == "0.1.1"
    assert set(sent["contexts"]) == {"runtime"}


def test_a_breadcrumb_carrying_data_is_dropped() -> None:
    assert scrub_breadcrumb({"category": "query", "data": {"body": "x"}}) is None
    assert scrub_breadcrumb({"category": "query"}) == {"category": "query"}


class Stub(Transport):
    """A transport that keeps what would have been sent."""

    sent: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.sent.append(item.payload.json)


@pytest.fixture
def stubbed() -> Iterator[type[Stub]]:
    Stub.sent = []
    yield Stub
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # back to a client that sends nothing


def crashing_app() -> TestClient:
    def crash(request: Request) -> Response:
        # Built at run time: Sentry sends the source line of a frame, which is code and not data.
        raise RuntimeError(" ".join(["Quokka", "retention", "is", "thirty", "days"]))

    return TestClient(Starlette(routes=[Route("/crash", crash, methods=["POST"])]), raise_server_exceptions=False)


def test_an_unhandled_error_sends_nothing_without_an_address(stubbed: type[Stub]) -> None:
    assert start_reporting(settings(""), transport=stubbed) is False

    answer = crashing_app().post("/crash", content="Quokka retention is thirty days")

    assert answer.status_code == 500
    assert stubbed.sent == []
    assert not sentry_sdk.get_client().is_active()


def test_an_unhandled_error_is_reported_scrubbed_with_an_address(stubbed: type[Stub]) -> None:
    assert start_reporting(settings(DSN), transport=stubbed) is True

    answer = crashing_app().post(
        "/crash?q=quokka+retention",
        content="Quokka retention is thirty days",
        headers={"Authorization": "Bearer smp_secret_personal_token", "Cookie": "session=cookie-value"},
    )
    sentry_sdk.flush()

    assert answer.status_code == 500
    assert len(stubbed.sent) == 1
    sent = json.dumps(stubbed.sent[0])
    assert "RuntimeError" in sent
    for secret in PRIVATE:
        assert secret not in sent, secret


def test_a_server_without_an_address_is_not_configured_to_report() -> None:
    assert Settings.from_env({}).sentry_dsn == ""
    assert Settings.from_env({"SHARED_MEMORY_SENTRY_DSN": f" {DSN} "}).sentry_dsn == DSN
