"""Signing in to the console with GitHub, and the sessions it gives out."""

from __future__ import annotations

import pytest

from tests.support import Console, ConsoleClient, RunningServer, Session, sign_in_error


def test_a_member_signs_in_with_their_linked_github_account(console: Console, signed_out: ConsoleClient) -> None:
    team, _ = console.a_team("olive-one")
    console.github.as_(101, "olive-one")

    signed_out.sign_in()

    assert signed_out.status() == {
        "signed_in": True,
        "github_sign_in": True,
        "member": {
            "employee_id": "E1001",
            "name": "Olive Owner",
            "team": team,
            "role": "owner",
            "leads_a_project": False,
        },
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
