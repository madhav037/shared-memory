"""The license key through the console JSON API and the Session driver (spec #416): an admin installs a key and sees the
team, cap and expiry; a member who isn't an admin can't; the cap follows the key; memory works the same without one.
The `install-license` command installs a key the same way, as the platform does on a hosted server's host (#470)."""

from __future__ import annotations

import dataclasses
import io
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory import cli
from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import LazyEmbedder
from tests.license_keys import TEST_PUBLIC_KEYS, a_key
from tests.support import (
    REPO_ROOT,
    Console,
    ConsoleClient,
    FakeGitHub,
    RunningServer,
    Session,
    TestClock,
    add,
    fresh_database,
    signed_in,
    signed_in_owner,
)


@pytest.fixture(scope="module")
def console(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Console]:
    with start_blocking_portal() as portal:
        memory = tmp_path_factory.mktemp("license-memory")
        sign_in = FakeGitHub(portal, Settings("", Path(memory), Path(memory)))
        clock = TestClock()  # 1 September 2026
        settings = Settings(
            database_url=fresh_database("shared_memory_license"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=sign_in.url,
            github_api_url=sign_in.url,
            rate_limit_on=False,
        )
        server = RunningServer(
            build_app(
                settings, clock=clock, embedder=LazyEmbedder(settings.model_cache), license_keys=TEST_PUBLIC_KEYS
            ),
            settings,
            clock,
            portal,
        )
        try:
            yield Console(server, sign_in, clock)
        finally:
            server.stop()
            sign_in.stop()


@pytest.fixture(autouse=True)
def no_key_installed(console: Console) -> None:
    console.server.app.state.licenses.clear()


def license_of(client: ConsoleClient) -> dict[str, Any]:
    response = client.get("/api/license")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def install(client: ConsoleClient, key: str) -> Any:
    return client.post_json("/api/license", {"key": key})


def test_a_server_with_no_key_is_unlicensed_and_says_so(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-none", 801)

    found = license_of(client)

    assert found["status"] == "unlicensed"
    assert found["team"] is None
    assert found["you_may_change"] is True


def test_an_admin_installs_a_key_and_sees_the_team_cap_and_expiry(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-install", 802)

    installed = install(client, a_key(team="Acme", member_cap=10, expires=date(2027, 9, 1), key_id="k-42"))

    assert installed.status_code == 200, installed.text
    found = license_of(client)
    assert (found["status"], found["team"], found["member_cap"], found["expires"], found["key_id"]) == (
        "licensed",
        "Acme",
        10,
        "2027-09-01",
        "k-42",
    )
    assert found["source"] == "console"
    assert client.get("/api/members").json()["member_cap"] == 10
    events = client.get("/api/audit").json()["events"]
    assert any(one["kind"] == "license_installed" for one in events)


def test_a_key_within_30_days_of_expiry_is_expiring(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-expiring", 803)

    install(client, a_key(expires=date(2026, 9, 20)))

    found = license_of(client)
    assert (found["status"], found["days_left"]) == ("expiring", 19)


def test_an_lapsed_key_shows_lapsed_and_still_caps_members(console: Console) -> None:
    client = console.client()
    owner = signed_in_owner(console, client, "olive-lic-lapsed", 804)

    install(client, a_key(member_cap=1, issued=date(2025, 1, 1), expires=date(2026, 1, 1)))

    assert license_of(client)["status"] == "lapsed"
    assert "member cap" in owner.refusal("add_member", member_id="emp-2", name="Dana Dev")


def test_a_tampered_or_wrongly_signed_key_is_refused_and_not_installed(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-bad", 805)
    head, payload, signature = a_key().split(".")

    for bad in (f"{head}.{payload}.{signature[:-3]}AAA", "not a key", a_key().replace("sm1.", "sm9.", 1)):
        refused = install(client, bad)
        assert refused.status_code == 403
        assert refused.json()["message"]

    assert license_of(client)["status"] == "unlicensed"


def test_a_member_who_is_not_an_admin_cannot_install_a_key(console: Console) -> None:
    owner_client = console.client()
    signed_in_owner(console, owner_client, "olive-lic-member", 806)
    add(owner_client, "emp-2", "Dana Dev", "dana-lic-member")
    dana = signed_in(console, "dana-lic-member", 807)

    refused = install(dana, a_key())

    assert refused.status_code == 403
    assert license_of(dana)["you_may_change"] is False
    assert license_of(owner_client)["status"] == "unlicensed"


def test_the_installed_key_sets_the_member_cap(console: Console) -> None:
    client = console.client()
    owner = signed_in_owner(console, client, "olive-lic-cap", 808)
    identity = console.server.app.state.identity
    install(client, a_key(member_cap=identity.members_in_use() + 1))

    owner.call("add_member", member_id="emp-2", name="Dana Dev")

    assert "member cap" in owner.refusal("add_member", member_id="emp-3", name="Eve Eng")


def test_recall_and_save_work_the_same_with_a_missing_or_lapsed_key(console: Console) -> None:
    client = console.client()
    owner = signed_in_owner(console, client, "olive-lic-memory", 809)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project)
    install(client, a_key(member_cap=1000, issued=date(2025, 1, 1), expires=date(2026, 1, 1)))

    for _ in ("a lapsed key", "no key"):
        saved = in_project.call(
            "remember", title="Use pnpm", summary="Always pnpm.", type="convention", body="We use pnpm everywhere."
        )
        assert in_project.call("read", path=saved["path"])["title"] == "Use pnpm"
        assert in_project.call("search", query="pnpm")
        console.server.app.state.licenses.clear()  # now no key at all


def test_a_key_in_the_environment_is_read_when_none_is_installed(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-env", 810)
    licenses = console.server.app.state.licenses
    environment = dataclasses.replace(licenses.settings, license_key=a_key(team="From env", member_cap=7))
    licenses.settings = environment

    try:
        found = license_of(client)
        assert (found["team"], found["member_cap"], found["source"]) == ("From env", 7, "environment")
    finally:
        licenses.settings = dataclasses.replace(environment, license_key="")


def test_an_invalid_key_in_the_environment_is_reported_and_changes_nothing(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-badenv", 811)
    licenses = console.server.app.state.licenses
    environment = dataclasses.replace(licenses.settings, license_key="garbage")
    licenses.settings = environment

    try:
        found = license_of(client)
        assert found["status"] == "invalid"
        assert found["reason"]
        assert client.get("/api/members").json()["member_cap"] is None
    finally:
        licenses.settings = dataclasses.replace(environment, license_key="")


def test_the_session_driver_is_unaffected_by_the_key_state(console: Console) -> None:
    client = console.client()
    owner = signed_in_owner(console, client, "olive-lic-driver", 812)
    assert isinstance(owner, Session)
    assert owner.call("create_project", name="Check")["project_id"]


def test_a_hosted_key_that_has_lapsed_shows_read_only_until_a_renewed_key_is_installed(console: Console) -> None:
    client = console.client()
    owner = signed_in_owner(console, client, "olive-lic-read-only", 813)
    install(client, a_key(member_cap=1000, issued=date(2025, 1, 1), expires=date(2026, 1, 1), hosted=True))

    assert license_of(client)["status"] == "read-only"
    assert "read-only" in owner.refusal("create_project", name="Late")

    renewed = install(client, a_key(member_cap=1000, expires=date(2027, 1, 1), hosted=True))

    assert renewed.status_code == 200, renewed.text
    assert license_of(client)["status"] == "licensed"
    assert owner.call("create_project", name="Paid")["project_id"]


def install_license(console: Console, key: str) -> tuple[int, str]:
    """`shared-memory install-license`, as the platform runs it on a hosted server's host (#470)."""
    out = io.StringIO()
    code = cli.run(["install-license", key], settings=console.server.settings, out=out, license_keys=TEST_PUBLIC_KEYS)
    return code, out.getvalue()


def vendor_installs(client: ConsoleClient) -> list[tuple[str, str]]:
    """The audit log's license installs, newest first: who installed which key."""
    events = client.get("/api/audit").json()["events"]
    return [(one["actor"], one["detail"]["key_id"]) for one in events if one["kind"] == "license_installed"]


def test_install_license_installs_a_key_server_wide_without_a_restart(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-cli", 814)
    assert license_of(client)["status"] == "unlicensed"

    code, printed = install_license(console, a_key(team="Acme", member_cap=10, expires=date(2027, 9, 1), key_id="k-cli"))
    console.clock.advance(seconds=5)  # how long a running server keeps the key it read before reading it again

    assert code == 0, printed
    assert "Acme" in printed
    found = license_of(client)
    assert (found["status"], found["team"], found["member_cap"], found["key_id"], found["source"]) == (
        "licensed",
        "Acme",
        10,
        "k-cli",
        "console",
    )
    assert client.get("/api/members").json()["member_cap"] == 10


def test_install_license_is_in_the_audit_log_as_installed_by_the_vendor(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-cli-audit", 815)

    install_license(console, a_key(key_id="k-cli-audit"))

    assert vendor_installs(client)[0] == ("vendor", "k-cli-audit")


def test_install_license_refuses_an_invalid_key_with_the_team_pages_answer_and_changes_nothing(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-cli-bad", 816)
    install(client, a_key(key_id="k-before"))
    head, payload, signature = a_key().split(".")

    for bad in (f"{head}.{payload}.{signature[:-3]}AAA", "not a key", a_key().replace("sm1.", "sm9.", 1)):
        code, printed = install_license(console, bad)
        console.clock.advance(seconds=5)

        assert code == 1
        assert printed.strip() == install(client, bad).json()["message"]

    assert license_of(client)["key_id"] == "k-before"
    assert vendor_installs(client)[0] == ("E1001", "k-before")


def test_install_license_replaces_a_key_installed_earlier(console: Console) -> None:
    client = console.client()
    signed_in_owner(console, client, "olive-lic-cli-renew", 817)
    install(client, a_key(member_cap=5, expires=date(2026, 9, 20), key_id="k-old", hosted=True))

    install_license(console, a_key(member_cap=15, expires=date(2027, 9, 20), key_id="k-renewed", hosted=True))
    console.clock.advance(seconds=5)

    found = license_of(client)
    assert (found["status"], found["member_cap"], found["key_id"]) == ("licensed", 15, "k-renewed")
