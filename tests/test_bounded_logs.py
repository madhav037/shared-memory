"""Container logs stay bounded, and a health check leaves no access-log line.

Docker's default json-file driver never rotates, so every service of a production compose file keeps a few files of
bounded size. The server's access log skips `GET /health`, which the deploy, Compose and an uptime check ask over and
over, and keeps every other request.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from shared_memory import app as app_module
from tests.support import REPO_ROOT

PRODUCTION = ("deploy/compose.yaml", "deploy/behind-a-proxy.yaml")
BOUND = {"driver": "json-file", "options": {"max-size": "20m", "max-file": "5"}}


class ComposeLoader(yaml.SafeLoader):
    """Compose's own `!override` tag, read as the value it marks."""


ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))  # type: ignore[arg-type]


def services_of(path: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.load((REPO_ROOT / path).read_text(encoding="utf-8"), Loader=ComposeLoader)  # noqa: S506
    services: dict[str, Any] = loaded["services"]
    return services


@pytest.mark.parametrize("path", PRODUCTION)
def test_every_service_of_a_production_compose_file_bounds_its_log(path: str) -> None:
    services = services_of(path)

    assert services, f"{path} has no services, so this test checks nothing"
    for name, service in services.items():
        assert service.get("logging") == BOUND, f"{path}: {name} keeps an unbounded log"


def test_the_base_file_bounds_all_four_services() -> None:
    assert set(services_of("deploy/compose.yaml")) == {"db", "server", "caddy", "backup"}


class Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append(record.getMessage())


@pytest.fixture
def served() -> Iterator[tuple[str, Lines]]:
    async def ok(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    app = Starlette(routes=[Route("/health", ok), Route("/api/things", ok)])
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="info", lifespan="on")
    server = uvicorn.Server(config)
    app_module.skip_health_checks_in_access_log()
    lines = Lines()
    access = logging.getLogger("uvicorn.access")
    access.addHandler(lines)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline and thread.is_alive(), "test server did not start"
        time.sleep(0.05)
    port: Any = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", lines
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        access.removeHandler(lines)


def test_a_health_check_writes_no_access_log_line_while_another_request_does(served: tuple[str, Lines]) -> None:
    url, lines = served

    assert httpx.get(f"{url}/health").status_code == 200
    assert httpx.get(f"{url}/health?probe=1").status_code == 200
    assert httpx.get(f"{url}/api/things").status_code == 200

    assert [line for line in lines.seen if "/health" in line] == []
    assert any("GET /api/things" in line for line in lines.seen)
