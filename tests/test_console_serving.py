"""How Caddy serves the console (deploy/Caddyfile, deploy/compose.yaml, console/public).

Caddy is configured in text, so its promises are checked here: the console travels compressed, its hashed assets are
cached for good while its page never is, the server's streams are never compressed, and a server keeps search engines
out unless whoever runs it says otherwise.
"""

from __future__ import annotations

import re
from pathlib import Path

from shared_memory.config import Settings
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


def header_value(name: str) -> str:
    """The value the Caddyfile gives a response header at the site level, for every answer it sends."""
    found = re.search(rf'^\t\t{re.escape(name)} "?(.*?)"?$', CADDYFILE, re.MULTILINE)
    assert found, f"the Caddyfile does not send {name}"
    return found.group(1)


def test_every_answer_tells_browsers_to_stay_on_https_and_not_to_guess_or_leak() -> None:
    assert re.search(r"^\theader \{$", CADDYFILE, re.MULTILINE), "security headers go in one site-level header block"
    assert header_value("Strict-Transport-Security").startswith("max-age=")
    assert header_value("X-Content-Type-Options") == "nosniff"
    assert header_value("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_the_console_cannot_be_framed_and_loads_only_from_its_own_origin() -> None:
    policy = {
        directive.split()[0]: directive.split()[1:]
        for directive in header_value("Content-Security-Policy").split(";")
        if directive.strip()
    }

    assert policy["frame-ancestors"] == ["'none'"], "a framed console invites clickjacking on pin, retire and decide"
    assert policy["default-src"] == ["'self'"]
    assert policy["script-src"] == ["'self'"], "the console's bundle is a same-origin module; nothing runs inline"
    assert "'unsafe-inline'" in policy["style-src"], "Mantine injects style tags and style attributes"
    assert policy["font-src"] == ["'self'", "data:"]
    assert policy["connect-src"] == ["'self'"]
    assert policy["object-src"] == ["'none'"]


def test_the_console_page_runs_no_inline_script_the_policy_would_block() -> None:
    page = (REPO_ROOT / "console" / "index.html").read_text(encoding="utf-8")

    for tag in re.findall(r"<script\b[^>]*>", page):
        assert "src=" in tag or "application/ld+json" in tag, f"an inline script the policy blocks: {tag}"


def handle_block(path: str) -> str:
    """The `handle` that passes one of the server's paths through."""
    found = re.search(rf"^\thandle {re.escape(path)} \{{\n(.*?)^\t\}}", CADDYFILE, re.MULTILINE | re.DOTALL)
    assert found, f"no handle for {path}"
    return found.group(1)


def test_caddy_counts_agent_calls_per_personal_token_and_falls_back_to_the_address() -> None:
    limits = re.search(r"^\(agent_limits\) \{\n(.*?)^\}", CADDYFILE, re.MULTILINE | re.DOTALL)
    assert limits, "no agent_limits snippet"
    by_token = re.search(r"zone by_token \{(.*?)\n\t\t\}", limits.group(1), re.DOTALL)
    by_address = re.search(r"zone by_address \{(.*?)\n\t\t\}", limits.group(1), re.DOTALL)
    assert by_token and by_address

    assert "header Authorization Bearer*" in by_token.group(1)
    assert "key {http.request.header.Authorization}" in by_token.group(1)
    assert "not header Authorization Bearer*" in by_address.group(1)
    assert "key {client_ip}" in by_address.group(1)
    for path in ("/mcp*", "/hooks/*"):
        assert "import agent_limits" in handle_block(path)


def test_caddy_counts_the_consoles_calls_per_address_with_room_for_an_office() -> None:
    api = handle_block("/api/*")

    assert "rate_limit {" in api
    assert "key {client_ip}" in api
    assert "{$CADDY_RATE_CONSOLE_PER_MINUTE:1200}" in api


def test_the_edge_ceilings_are_at_or_above_the_servers_and_set_in_the_environment() -> None:
    server = Settings("", Path("."), Path("."))
    ceilings = {
        "CADDY_RATE_TOKEN_PER_MINUTE": server.rate_limit_token_per_minute,
        "CADDY_RATE_ADDRESS_PER_MINUTE": server.rate_limit_address_per_minute,
        "CADDY_RATE_CONSOLE_PER_MINUTE": server.rate_limit_console_per_minute,
    }
    for name, serves in ceilings.items():
        default = re.search(r"\{\$%s:(\d+)\}" % name, CADDYFILE)
        assert default, f"the Caddyfile does not read {name}"
        assert int(default.group(1)) >= serves, f"{name} is below the server's own limit"
        assert f"{name}: $" in COMPOSE


def test_the_consoles_image_builds_caddy_with_the_rate_limit_module() -> None:
    dockerfile = (DEPLOY / "console" / "Dockerfile").read_text(encoding="utf-8")

    assert "xcaddy build --with github.com/mholt/caddy-ratelimit" in dockerfile
    assert "COPY --from=caddy /usr/bin/caddy /usr/bin/caddy" in dockerfile


def test_the_example_nginx_site_has_the_equivalent_limit() -> None:
    nginx = (DEPLOY / "nginx-site.conf.example").read_text(encoding="utf-8")

    assert "limit_req_zone $shared_memory_caller" in nginx
    assert "$http_authorization" in nginx and "$binary_remote_addr" in nginx
    assert "limit_req zone=shared_memory" in nginx
    assert "limit_req_status 429;" in nginx
