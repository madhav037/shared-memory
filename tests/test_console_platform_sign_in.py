"""Signing in to a hosted server's console by a sign-in the platform hands over (#471)."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from shared_memory import platform_sign_in

from shared_memory.console_sessions import NONCE_COOKIE
from tests.support import Console, ConsoleClient, HostedConsole, sign_in_error


@pytest.fixture
def hosted(hosted_console: HostedConsole) -> Iterator[ConsoleClient]:
    """A browser on the hosted server, signed out."""
    client = ConsoleClient(hosted_console.server)
    try:
        yield client
    finally:
        client.close()


def test_choosing_to_sign_in_sends_the_member_to_the_platform_with_the_subdomain_a_return_address_and_a_nonce(
    hosted_console: HostedConsole, hosted: ConsoleClient
) -> None:
    where = urlsplit(hosted.start_sign_in())

    assert f"{where.scheme}://{where.netloc}{where.path}" == f"{hosted_console.platform.url}/sign-in"
    query = parse_qs(where.query)
    nonce = hosted.cookie(NONCE_COOKIE)
    assert nonce
    assert query == {
        "subdomain": ["acme"],
        "return_to": [f"{hosted_console.server.url}/api/sign-in/platform/callback"],
        "nonce": [nonce],
    }


def test_each_sign_in_gets_its_own_nonce(hosted_console: HostedConsole, hosted: ConsoleClient) -> None:
    first = parse_qs(urlsplit(hosted.start_sign_in()).query)["nonce"]
    second = parse_qs(urlsplit(hosted.start_sign_in()).query)["nonce"]

    assert first != second


def test_a_member_signs_in_by_the_sign_in_the_platform_hands_over(
    hosted_console: HostedConsole, hosted: ConsoleClient
) -> None:
    team, _ = hosted_console.a_team("hana-one")
    hosted_console.platform.as_(201, "hana-one")

    hosted.sign_in()

    assert hosted.cookie(NONCE_COOKIE) is None
    assert hosted.status() == {
        "signed_in": True,
        "github_sign_in": True,
        "member": {
            "member_id": "E1001",
            "name": "Olive Owner",
            "team": team,
            "role": "owner",
            "leads_a_project": False,
        },
        "server_url": hosted_console.server.url,
        "platform_url": hosted_console.platform.url,
    }


def test_a_sign_in_whose_signature_does_not_check_out_is_refused(
    hosted_console: HostedConsole, hosted: ConsoleClient
) -> None:
    hosted_console.a_team("hana-two")
    hosted_console.platform.as_(202, "hana-two")
    hosted_console.platform.go_wrong(forged=True)

    landed = hosted.sign_in()

    assert "couldn't be checked" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_for_another_subdomain_is_refused(hosted_console: HostedConsole, hosted: ConsoleClient) -> None:
    hosted_console.a_team("hana-three")
    hosted_console.platform.as_(203, "hana-three")
    hosted_console.platform.go_wrong(subdomain="globex")

    landed = hosted.sign_in()

    assert "for another team's server" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_that_has_expired_is_refused(hosted_console: HostedConsole, hosted: ConsoleClient) -> None:
    hosted_console.a_team("hana-four")
    hosted_console.platform.as_(204, "hana-four")
    hosted_console.platform.go_wrong(expired=True)

    landed = hosted.sign_in()

    assert "took too long" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_held_back_until_it_expires_is_refused(hosted_console: HostedConsole, hosted: ConsoleClient) -> None:
    hosted_console.a_team("hana-five")
    hosted_console.platform.as_(205, "hana-five")
    handed_back = handed_back_to(hosted)
    hosted_console.clock.advance(minutes=6)

    try:
        landed = hosted.get(handed_back)
    finally:
        hosted_console.clock.advance(minutes=-6)

    assert "took too long" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_expiring_too_far_ahead_is_refused(hosted_console: HostedConsole, hosted: ConsoleClient) -> None:
    hosted_console.a_team("hana-nine")
    hosted_console.platform.as_(209, "hana-nine")
    hosted_console.platform.go_wrong(far_ahead=True)

    landed = hosted.sign_in()

    assert "couldn't be checked" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_handed_to_a_browser_that_did_not_start_it_is_refused(
    hosted_console: HostedConsole, hosted: ConsoleClient
) -> None:
    hosted_console.a_team("hana-ten")
    hosted_console.platform.as_(210, "hana-ten")
    handed_back = handed_back_to(hosted)
    colleague = ConsoleClient(hosted_console.server)
    try:
        landed = colleague.get(handed_back)
        assert "didn't start in this browser" in sign_in_error(landed)
        assert colleague.status()["signed_in"] is False
    finally:
        colleague.close()

    # Turning the colleague away didn't spend the sign-in: the browser that started it still finishes it.
    assert sign_in_error(hosted.get(handed_back)) == ""
    assert hosted.status()["signed_in"] is True


def test_a_sign_in_carrying_another_nonce_is_refused(hosted_console: HostedConsole, hosted: ConsoleClient) -> None:
    hosted_console.a_team("hana-eleven")
    hosted_console.platform.as_(211, "hana-eleven")
    hosted_console.platform.go_wrong(nonce="someone-elses-nonce")

    landed = hosted.sign_in()

    assert "didn't start in this browser" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_handed_back_a_second_time_is_refused(
    hosted_console: HostedConsole, hosted: ConsoleClient
) -> None:
    hosted_console.a_team("hana-twelve")
    hosted_console.platform.as_(212, "hana-twelve")
    hosted.sign_in()
    handed_back = hosted_console.platform.last
    hosted.sign_out()

    landed = hosted.get(handed_back)

    assert "didn't start in this browser" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_is_accepted_only_once_even_with_its_nonce(
    hosted_console: HostedConsole, hosted: ConsoleClient
) -> None:
    hosted_console.a_team("hana-six")
    hosted_console.platform.as_(206, "hana-six")
    hosted.sign_in()
    handed_back = hosted_console.platform.last
    hosted.sign_out()
    hosted.set_cookie(NONCE_COOKIE, hosted_console.platform.last_nonce)

    landed = hosted.get(handed_back)

    assert "already used" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_github_account_nobody_has_linked_is_refused_as_github_sign_in_refuses_it(
    hosted_console: HostedConsole, hosted: ConsoleClient
) -> None:
    hosted_console.a_team("hana-seven")
    hosted_console.platform.as_(207, "a-stranger")

    landed = hosted.sign_in()

    assert "The GitHub account @a-stranger isn't linked to a member" in sign_in_error(landed)
    assert hosted.status()["signed_in"] is False


def test_a_sign_in_with_nothing_handed_over_is_refused(hosted: ConsoleClient) -> None:
    landed = hosted.get("/api/sign-in/platform/callback")

    assert "didn't finish" in sign_in_error(landed)


def test_a_server_with_its_own_github_app_takes_no_sign_in_from_the_platform(
    hosted_console: HostedConsole, console: Console, signed_out: ConsoleClient
) -> None:
    console.a_team("hana-eight")
    hosted_console.platform.as_(208, "hana-eight")

    landed = signed_out.get(handed_over(hosted_console, f"{console.server.url}/api/sign-in/platform/callback"))

    assert "doesn't take sign-ins from the platform" in sign_in_error(landed)
    assert signed_out.status()["signed_in"] is False


def handed_back_to(browser: ConsoleClient) -> str:
    """The address the fake platform hands a sign-in this browser started back to, without going there."""
    sent = httpx.get(browser.start_sign_in(), follow_redirects=False)
    assert sent.status_code == 302, sent.text
    return str(sent.headers["location"])


def handed_over(hosted_console: HostedConsole, return_to: str) -> str:
    """The address the fake platform hands a sign-in for `acme` back to, without going there."""
    sent = httpx.get(
        f"{hosted_console.platform.url}/sign-in",
        params={"subdomain": "acme", "return_to": return_to, "nonce": "a-nonce"},
        follow_redirects=False,
    )
    assert sent.status_code == 302, sent.text
    return str(sent.headers["location"])


def test_a_sign_in_whose_payload_carries_no_nonce_cannot_be_trusted() -> None:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    payload = json.dumps(
        {"expires": 1763112300, "github_id": 1, "github_login": "olive", "id": "kq3", "subdomain": "acme"}
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = base64.urlsafe_b64encode(key.sign(encoded)).rstrip(b"=")

    with pytest.raises(platform_sign_in.InvalidSignIn):
        platform_sign_in.verify(f"{encoded.decode()}.{signature.decode()}", public)
