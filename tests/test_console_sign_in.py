"""Signing in to the console with GitHub, and the sessions it gives out."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import (
    REPO_ROOT,
    ConsoleClient,
    FakeGitHub,
    RunningServer,
    Session,
    TestClock,
    fresh_database,
    sign_in_error,
)


@dataclass
class Console:
    """A server with GitHub sign-in set up, and the fake GitHub it signs people in through."""

    server: RunningServer
    github: FakeGitHub
    clock: TestClock

    def client(self) -> ConsoleClient:
        return ConsoleClient(self.server)

    def a_team(self, github_login: str) -> tuple[str, str]:
        """A team whose owner signs in as this GitHub account; returns the team's code and the owner's token."""
        code = f"team-{uuid.uuid4().hex[:8]}"
        printed = self.server.run_cli(
            "setup", "--team", code, "--owner-employee-id", "E1001", "--owner-name", "Olive Owner",
            "--owner-github", github_login,
        )  # fmt: skip
        token = next(line.split(":", 1)[1].strip() for line in printed.splitlines() if line.startswith("Owner personal"))
        return code, token


@pytest.fixture(scope="module")
def console(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Console]:
    with start_blocking_portal() as portal:
        memory = tmp_path_factory.mktemp("console-memory")
        github = FakeGitHub(portal, Settings("", Path(memory), Path(memory)))
        clock = TestClock()
        settings = Settings(
            database_url=fresh_database("shared_memory_console"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=github.url,
            github_api_url=github.url,
        )
        server = RunningServer(build_app(settings, clock=clock), settings, clock, portal)
        try:
            yield Console(server, github, clock)
        finally:
            server.stop()
            github.stop()


@pytest.fixture
def signed_out(console: Console) -> Iterator[ConsoleClient]:
    console.clock.now = TestClock().now
    client = console.client()
    try:
        yield client
    finally:
        client.close()


def test_a_member_signs_in_with_their_linked_github_account(console: Console, signed_out: ConsoleClient) -> None:
    team, _ = console.a_team("olive-one")
    console.github.as_(101, "olive-one")

    signed_out.sign_in()

    assert signed_out.status() == {
        "signed_in": True,
        "github_sign_in": True,
        "member": {"employee_id": "E1001", "name": "Olive Owner", "team": team, "role": "owner"},
    }


def test_a_github_account_nobody_has_linked_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-two")
    console.github.as_(102, "a-stranger")

    landed = signed_out.sign_in()

    assert "isn't linked to a member" in sign_in_error(landed)
    assert signed_out.status()["signed_in"] is False


def test_a_removed_member_can_no_longer_sign_in(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-three")
    Session(console.server, owner_token).call("add_member", employee_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--team", team, "--employee-id", "emp-2", "--github", "dana-three")
    Session(console.server, owner_token).call("remove_member", employee_id="emp-2")
    console.github.as_(103, "dana-three")

    landed = signed_out.sign_in()

    assert "removed from this team" in sign_in_error(landed)
    assert signed_out.status()["signed_in"] is False


def test_a_renamed_github_account_still_signs_in(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-four")
    console.github.as_(104, "olive-four")
    signed_out.sign_in()
    signed_out.sign_out()

    console.github.as_(104, "olive-four-renamed")
    signed_out.sign_in()

    assert signed_out.status()["member"]["employee_id"] == "E1001"


def test_one_github_account_cannot_belong_to_two_members(console: Console) -> None:
    team, owner_token = console.a_team("olive-five")
    Session(console.server, owner_token).call("add_member", employee_id="emp-2", name="Dana Dev")

    with pytest.raises(RuntimeError, match="already linked to 'E1001'"):
        console.server.run_cli("link-github", "--team", team, "--employee-id", "emp-2", "--github", "olive-five")


def test_signing_out_ends_the_session(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-six")
    console.github.as_(106, "olive-six")
    signed_out.sign_in()

    signed_out.sign_out()

    assert signed_out.status()["signed_in"] is False


def test_a_session_is_refused_without_the_consoles_own_header(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-seven")
    console.github.as_(107, "olive-seven")
    signed_out.sign_in()

    refused = signed_out.sign_out(with_header=False)

    assert refused.status_code == 403
    assert signed_out.status()["signed_in"] is True


def test_a_session_expires_after_a_day_without_use(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-eight")
    console.github.as_(108, "olive-eight")
    signed_out.sign_in()

    console.clock.advance(hours=25)

    assert signed_out.status()["signed_in"] is False


def test_a_session_ends_when_the_member_is_removed(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-nine")
    Session(console.server, owner_token).call("add_member", employee_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--team", team, "--employee-id", "emp-2", "--github", "dana-nine")
    console.github.as_(109, "dana-nine")
    signed_out.sign_in()
    assert signed_out.status()["signed_in"] is True

    Session(console.server, owner_token).call("remove_member", employee_id="emp-2")

    assert signed_out.status()["signed_in"] is False


def test_a_sign_in_that_did_not_start_here_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    landed = signed_out.get("/api/sign-in/github/callback?code=fake-code&state=made-up")

    assert "didn't come from this console" in sign_in_error(landed)


def test_a_server_without_github_cannot_sign_anyone_in(server: RunningServer) -> None:
    client = ConsoleClient(server)
    try:
        assert client.status() == {"signed_in": False, "github_sign_in": False, "member": None}
        landed = client.sign_in()
        assert "isn't set up on this server" in sign_in_error(landed)
    finally:
        client.close()
