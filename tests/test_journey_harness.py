"""The browser journeys run against the two servers Playwright starts for them, and nothing else.

`reuseExistingServer` attaches Playwright to whatever already answers on a port, silently. A developer's own
`npm run preview` answers on the same port and proxies to the Docker server on :8000, not to the seeded journey
server on :8123 — so a reused preview signs the journeys in against a server that has never heard of the account
they use, and thirteen of fifteen journeys fail on a timeout that has nothing to do with the console.

A reused journey server is the quieter half of the same fault: its memory is whatever the last run left behind,
and the journeys retire and rename things.

So these tests watch the two properties that make either impossible: every server the journeys use is one they
started, and the port they use is not a port anything else listens on.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from tests.console_e2e_server import CONSOLE, DEFAULT_GITHUB_PORT, github_port
from tests.support import REPO_ROOT

PLAYWRIGHT_CONFIG = (REPO_ROOT / "console" / "playwright.config.ts").read_text(encoding="utf-8")
VITE_CONFIG = (REPO_ROOT / "console" / "vite.config.ts").read_text(encoding="utf-8")


def journeys_console_url() -> str:
    """The address the journeys point the browser at."""
    found = re.search(r'const consoleUrl = "([^"]+)"', PLAYWRIGHT_CONFIG)
    assert found, "playwright.config.ts no longer declares consoleUrl"
    return found.group(1)


def test_the_journeys_never_attach_to_a_server_they_did_not_start() -> None:
    reuse = [value.strip() for value in re.findall(r"reuseExistingServer:\s*([^,\n]+)", PLAYWRIGHT_CONFIG)]
    servers = re.findall(r"^\s*command:\s*", PLAYWRIGHT_CONFIG, re.MULTILINE)

    assert len(reuse) == len(servers), "every webServer entry has to say whether it reuses, and say no"
    assert reuse == ["false"] * len(servers), f"the journeys would attach to a server they did not start: {reuse}"


def test_the_console_the_journeys_open_is_the_one_the_journey_server_redirects_to() -> None:
    """Signing in bounces through the fake GitHub and back to `console_url`; a mismatch strands the browser."""
    assert journeys_console_url() == CONSOLE


def test_the_journeys_do_not_share_a_port_with_a_developers_preview() -> None:
    developers = re.search(r"preview:\s*\{[^}]*?port:\s*(\d+)", VITE_CONFIG)
    assert developers, "vite.config.ts no longer declares the preview port"
    journeys = urlparse(journeys_console_url()).port

    assert journeys != int(developers.group(1)), "a developer's preview and the journeys want the same port"
    assert f"--port {journeys}" in PLAYWRIGHT_CONFIG, "the journeys' preview is not pinned to the port they open"


HELPERS = (REPO_ROOT / "console" / "e2e" / "helpers.ts").read_text(encoding="utf-8")
COMPOSE = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")


def test_the_journeys_fake_github_can_move_to_a_port_nothing_else_holds() -> None:
    """A local sign-in stack, or a second run of the journeys, may already hold the default port."""
    assert github_port({}) == DEFAULT_GITHUB_PORT
    assert github_port({"SHARED_MEMORY_E2E_GITHUB_PORT": "8199"}) == 8199


def test_the_browser_and_the_journey_server_agree_on_where_the_fake_github_is() -> None:
    found = re.search(r'process\.env\.SHARED_MEMORY_E2E_GITHUB_PORT \?\? "(\d+)"', HELPERS)
    assert found, "helpers.ts no longer reads the fake GitHub's port from SHARED_MEMORY_E2E_GITHUB_PORT"
    assert int(found.group(1)) == DEFAULT_GITHUB_PORT, "the browser and the journey server default to different ports"

    hard_coded = [
        path.name
        for path in (REPO_ROOT / "console" / "e2e").glob("*.ts")
        if path.name != "helpers.ts" and re.search(r"127\.0\.0\.1:\d+", path.read_text(encoding="utf-8"))
    ]
    assert hard_coded == [], f"these journeys name the fake GitHub's address themselves: {hard_coded}"


def test_the_journeys_fake_github_is_not_on_a_port_the_local_stack_publishes() -> None:
    published = {int(port) for port in re.findall(r'"(\d+):\d+"', COMPOSE)}

    assert DEFAULT_GITHUB_PORT not in published
