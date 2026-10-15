"""The stack behind a web server the host already runs (deploy/behind-a-proxy.yaml).

These files are read by Compose, Caddy, nginx and a shell, not by Python, so what holds them together is checked
here: Caddy is reachable only from the host, the example nginx site points at the port the stack listens on, and the
server believes the scheme it is forwarded only because nothing can reach it any other way.
"""

from __future__ import annotations

import re

from tests.support import REPO_ROOT

DEPLOY = REPO_ROOT / "deploy"
COMPOSE = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
OVERRIDE = (DEPLOY / "behind-a-proxy.yaml").read_text(encoding="utf-8")
NGINX = (DEPLOY / "nginx-site.conf.example").read_text(encoding="utf-8")
CADDYFILE = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")


def service(compose: str, name: str) -> str:
    """One service's block in a Compose file, up to the next service or top-level key."""
    found = re.search(rf"^  {name}:\n(.*?)(?=^  \w[\w-]*:\n|^\S|\Z)", compose, re.MULTILINE | re.DOTALL)
    assert found, f"no {name} service"
    return found.group(1)


def test_behind_a_proxy_caddy_listens_on_the_hosts_loopback_only() -> None:
    caddy = service(OVERRIDE, "caddy")

    assert "ports: !override" in caddy, "the base file's 80 and 443 would be published as well"
    published = re.findall(r'^\s+- "([^"]+)"', caddy, re.MULTILINE)
    assert published == ["127.0.0.1:${SHARED_MEMORY_LOCAL_PORT:-8180}:80"]
    assert 'CADDY_SITE_ADDRESS: ":80"' in caddy, "Caddy would try for a certificate the host's web server holds"


def test_the_example_nginx_site_passes_the_domain_to_that_port_with_its_scheme() -> None:
    default_port = re.search(r"SHARED_MEMORY_LOCAL_PORT:-(\d+)", OVERRIDE)
    assert default_port

    assert f"proxy_pass http://127.0.0.1:{default_port.group(1)};" in NGINX
    assert "proxy_set_header Host $host;" in NGINX
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in NGINX
    assert "proxy_buffering off;" in NGINX, "MCP answers stream"


def test_the_server_believes_forwarded_headers_only_because_nothing_reaches_it_but_caddy() -> None:
    server = service(COMPOSE, "server")

    assert 'FORWARDED_ALLOW_IPS: "*"' in server, "the addresses the server hands out would say http"
    assert "ports:" not in server, "a published server port would let anyone forge X-Forwarded-Proto"


def test_caddy_believes_forwarded_headers_only_when_put_behind_a_proxy() -> None:
    assert "trusted_proxies static {$CADDY_TRUSTED_PROXIES:127.0.0.1/32}" in CADDYFILE
    assert "{$CADDY_SITE_ADDRESS} {" in CADDYFILE
    assert "CADDY_SITE_ADDRESS: ${SHARED_MEMORY_DOMAIN}" in service(COMPOSE, "caddy")


def test_the_preflight_and_the_deployment_steps_know_the_mode() -> None:
    preflight = (DEPLOY / "preflight.sh").read_text(encoding="utf-8")
    steps = (REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")

    assert "*behind-a-proxy.yaml*)" in preflight, "the preflight would refuse a host whose web server holds 80 and 443"
    assert "## Behind a web server the host already runs" in steps
    assert "COMPOSE_FILE=compose.yaml:behind-a-proxy.yaml" in steps
    assert "# COMPOSE_FILE=compose.yaml:behind-a-proxy.yaml" in example
