"""The compose files for running on your own machine publish nothing beyond it.

Docker publishes a port on every interface unless told otherwise, ahead of the host's firewall rules, and the local
Postgres has a well-known password. Production (`deploy/`) is behind Caddy and is checked elsewhere.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCAL = ("compose.yaml", "smoke/stress-compose.yaml")


def published(path: str) -> list[str]:
    services = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))["services"]
    return [str(port) for service in services.values() for port in service.get("ports", [])]


@pytest.mark.parametrize("path", LOCAL)
def test_a_local_compose_file_publishes_its_ports_on_this_machine_only(path: str) -> None:
    ports = published(path)

    assert ports, f"{path} publishes no port, so this test checks nothing"
    assert [port for port in ports if not port.startswith("127.0.0.1:")] == []
