"""How Caddy serves the console (deploy/Caddyfile, deploy/compose.yaml, console/public).

Caddy is configured in text, so its promises are checked here: the console travels compressed, its hashed assets are
cached for good while its page never is, the server's streams are never compressed, and a server keeps search engines
out unless whoever runs it says otherwise.
"""

from __future__ import annotations

import re

from tests.support import REPO_ROOT

DEPLOY = REPO_ROOT / "deploy"
CADDYFILE = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
COMPOSE = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
ROBOTS = REPO_ROOT / "console" / "public" / "robots.txt"


def console_block() -> str:
    """The catch-all `handle` that serves the console's files."""
    found = re.search(r"^\thandle \{\n(.*?)^\t\}", CADDYFILE, re.MULTILINE | re.DOTALL)
    assert found, "no catch-all handle for the console"
    return found.group(1)


def test_the_console_travels_compressed_and_the_servers_streams_do_not() -> None:
    assert "encode zstd gzip" in console_block()
    assert CADDYFILE.count("encode ") == 1, "compressing /mcp or /api would hold back streamed answers"


def test_the_consoles_hashed_assets_are_cached_for_good_and_its_page_never_is() -> None:
    block = console_block()

    assert "@assets path /assets/*" in block
    assert 'header @assets Cache-Control "public, max-age=31536000, immutable"' in block
    assert 'header @page Cache-Control "no-cache"' in block, "a release would reach browsers only when a cache expired"


def test_search_engines_are_kept_out_unless_whoever_runs_the_server_lets_them_in() -> None:
    assert "header X-Robots-Tag {$CADDY_ROBOTS_TAG:noindex}" in CADDYFILE
    assert "CADDY_ROBOTS_TAG: ${SHARED_MEMORY_ROBOTS_TAG:-noindex}" in COMPOSE


def test_robots_txt_is_a_real_file_that_keeps_crawlers_off_the_servers_own_addresses() -> None:
    robots = ROBOTS.read_text(encoding="utf-8")

    assert robots.startswith("User-agent: *\n")
    for address in ("/api/", "/mcp", "/hooks/"):
        assert f"Disallow: {address}\n" in robots
