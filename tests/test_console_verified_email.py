"""A GitHub sign-in fills in the member's verified email (#679), and admins see it with the sign-in methods."""

from __future__ import annotations

import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from shared_memory.console_sessions import NONCE_COOKIE
from tests.support import Console, ConsoleClient, add, sign_in_error


def entry(email: str, primary: bool = True, verified: bool = True) -> dict[str, Any]:
    return {"email": email, "primary": primary, "verified": verified, "visibility": None}


def owner_signed_in(console: Console, login: str, account: int, *emails: dict[str, Any]) -> ConsoleClient:
    """A company whose owner signs in with GitHub, which lists these emails for them."""
    console.a_company(login)
    return signed_in_with(console, login, account, *emails)


def signed_in_with(console: Console, login: str, account: int, *emails: dict[str, Any]) -> ConsoleClient:
    client = console.client()
    console.github.as_(account, login)
    console.github.has_emails(*emails)
    landed = client.sign_in()
    assert client.status()["signed_in"] is True, sign_in_error(landed)
    return client


def listed(client: ConsoleClient) -> dict[str, dict[str, Any]]:
    response = client.get("/api/members")
    assert response.status_code == 200, response.text
    return {one["member_id"]: one for one in response.json()["members"]}


def sent_back_to(console: Console, browser: ConsoleClient) -> str:
    """The callback address GitHub sends a sign-in this browser started back to, without going there."""
    sent = httpx.get(browser.start_sign_in(), follow_redirects=False)
    assert sent.status_code == 302, sent.text
    return str(sent.headers["location"])


def test_a_github_sign_in_stores_the_accounts_primary_verified_email_when_the_member_has_none(
    console: Console,
) -> None:
    owner = owner_signed_in(console, "olive-ve-one", 701, entry(" Olive@Example.com "))

    assert listed(owner)["E1001"]["verified_email"] == "Olive@Example.com"


def test_the_sign_in_asks_github_for_the_email_scope(console: Console, signed_out: ConsoleClient) -> None:
    sent_to = signed_out.start_sign_in()

    assert parse_qs(urlparse(sent_to).query)["scope"] == ["read:user user:email"]


@pytest.mark.parametrize(
    "emails",
    [
        [entry("a@example.com", verified=False)],
        [entry("a@example.com", primary=False)],
        [{"email": "a@example.com", "primary": "true", "verified": "true"}],
        [{"email": "a@example.com", "primary": 1, "verified": 1}],
        [{"email": "a@example.com", "primary": True}],
        [{"email": "  ", "primary": True, "verified": True}],
        [{"email": 7, "primary": True, "verified": True}],
    ],
    ids=["unverified", "not-primary", "string-booleans", "numbers", "no-verified-flag", "blank", "not-a-string"],
)
def test_an_unverified_github_email_is_never_stored(
    console: Console, emails: list[dict[str, Any]], request: pytest.FixtureRequest
) -> None:
    case = next(iter(request.node.callspec.indices.values()))
    owner = owner_signed_in(console, f"olive-ve-two-{case}", 720 + case, *emails)

    assert listed(owner)["E1001"]["verified_email"] is None


def test_the_primary_verified_email_is_the_one_stored_among_several(console: Console) -> None:
    owner = owner_signed_in(
        console,
        "olive-ve-three",
        703,
        entry("other@example.com", primary=False),
        entry("main@example.com"),
    )

    assert listed(owner)["E1001"]["verified_email"] == "main@example.com"


def test_a_github_sign_in_never_replaces_a_verified_email_the_member_already_has(console: Console) -> None:
    owner = owner_signed_in(console, "olive-ve-four", 704, entry("first@example.com"))
    owner.sign_out()

    again = signed_in_with(console, "olive-ve-four", 704, entry("second@example.com"))

    assert listed(again)["E1001"]["verified_email"] == "first@example.com"


def test_an_email_another_member_holds_in_any_case_is_not_stored_and_sign_in_still_works(console: Console) -> None:
    owner = owner_signed_in(console, "olive-ve-five", 705, entry("Shared@Example.com"))
    add(owner, "emp-2", "Dana Dev", "dana-ve-five")

    dana = signed_in_with(console, "dana-ve-five", 706, entry("shared@example.com"))

    assert dana.status()["member"]["member_id"] == "emp-2"
    assert listed(owner)["emp-2"]["verified_email"] is None
    assert listed(owner)["E1001"]["verified_email"] == "Shared@Example.com"


def test_two_sign_ins_racing_for_one_email_both_sign_in_and_one_holds_it(console: Console) -> None:
    owner = owner_signed_in(console, "olive-ve-six", 707)
    add(owner, "emp-2", "Dana Dev", "dana-ve-six")
    add(owner, "emp-3", "Eli Eng", "eli-ve-six")
    console.github.has_emails(entry("race@example.com"))
    browsers = [console.client(), console.client()]
    callbacks = []
    for browser, login, account in zip(browsers, ["dana-ve-six", "eli-ve-six"], [708, 709], strict=True):
        console.github.as_(account, login)
        console.github.has_emails(entry("race@example.com"))
        callbacks.append(httpx.get(browser.start_sign_in(), follow_redirects=False).headers["location"])
    landed: list[Any] = [None, None]
    barrier = threading.Barrier(2)

    def finish(index: int) -> None:
        barrier.wait()
        landed[index] = browsers[index].get(callbacks[index])

    threads = [threading.Thread(target=finish, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [browser.status()["signed_in"] for browser in browsers] == [True, True], [
        sign_in_error(one) for one in landed
    ]
    held = [one["verified_email"] for one in listed(owner).values()]
    assert held.count("race@example.com") == 1


@pytest.mark.parametrize(
    "status, raw",
    [
        (403, "{}"),
        (404, "{}"),
        (500, "oops"),
        (200, "not json at all"),
        (200, '{"message": "an object"}'),
        (200, '[1, "x"]'),
        (200, "null"),
    ],
    ids=["403", "404", "500", "bad-json", "wrong-shape-object", "wrong-shape-entries", "null"],
)
def test_a_member_without_any_verified_github_email_still_signs_in(
    console: Console, status: int, raw: str, request: pytest.FixtureRequest
) -> None:
    case = next(iter(request.node.callspec.indices.values()))
    console.a_company(f"olive-ve-seven-{case}")
    console.github.as_(730 + case, f"olive-ve-seven-{case}")
    console.github.emails_status = status
    console.github.emails_raw = raw
    client = console.client()

    client.sign_in()

    assert client.status()["signed_in"] is True
    assert listed(client)["E1001"]["verified_email"] is None


def test_a_github_that_lists_no_emails_at_all_still_signs_the_member_in(console: Console) -> None:
    owner = owner_signed_in(console, "olive-ve-eight", 711)

    assert owner.status()["signed_in"] is True
    assert listed(owner)["E1001"]["verified_email"] is None


def test_a_sign_in_that_fails_its_state_check_never_asks_github_for_emails(console: Console) -> None:
    console.a_company("olive-ve-nine")
    console.github.as_(712, "olive-ve-nine")
    console.github.has_emails(entry("nine@example.com"))
    client = console.client()
    client.set_cookie(NONCE_COOKIE, "made-up")  # so it is the state, not the browser, that is refused

    landed = client.get("/api/sign-in/github/callback?code=fake-code&state=made-up")

    assert "didn't come from this console" in sign_in_error(landed)
    assert console.github.email_calls == 0


def test_a_sign_in_from_another_browser_never_asks_github_for_emails(console: Console) -> None:
    console.a_company("olive-ve-ten")
    console.github.as_(713, "olive-ve-ten")
    console.github.has_emails(entry("ten@example.com"))
    callback = sent_back_to(console, console.client())

    landed = console.client().get(callback)

    assert "didn't start in this browser" in sign_in_error(landed)
    assert console.github.email_calls == 0


def test_the_member_list_shows_admins_each_members_verified_email_and_sign_in_methods(console: Console) -> None:
    owner = owner_signed_in(console, "olive-ve-eleven", 714, entry("olive@example.com"))
    add(owner, "emp-2", "Dana Dev", "dana-ve-eleven")
    add(owner, "emp-3", "Eli Eng")

    seen = listed(owner)

    assert (seen["E1001"]["verified_email"], seen["E1001"]["sign_in_methods"]) == ("olive@example.com", ["github"])
    assert (seen["emp-2"]["verified_email"], seen["emp-2"]["sign_in_methods"]) == (None, ["github"])
    assert (seen["emp-3"]["verified_email"], seen["emp-3"]["sign_in_methods"]) == (None, [])


def test_an_admin_who_is_not_the_owner_sees_them_too(console: Console) -> None:
    owner = owner_signed_in(console, "olive-ve-twelve", 715, entry("olive@example.com"))
    add(owner, "emp-2", "Dana Dev", "dana-ve-twelve")
    assert owner.post_json("/api/members/emp-2/admin", {"admin": True}).status_code == 200
    dana = signed_in_with(console, "dana-ve-twelve", 716, entry("dana@example.com"))

    seen = listed(dana)

    assert seen["E1001"]["verified_email"] == "olive@example.com"
    assert seen["emp-2"]["sign_in_methods"] == ["github"]


def test_a_member_who_is_not_an_admin_gets_no_emails_and_no_sign_in_methods(console: Console) -> None:
    owner = owner_signed_in(console, "olive-ve-thirteen", 717, entry("olive@example.com"))
    add(owner, "emp-2", "Dana Dev", "dana-ve-thirteen")
    dana = signed_in_with(console, "dana-ve-thirteen", 718, entry("dana@example.com"))
    assert listed(owner)["emp-2"]["verified_email"] == "dana@example.com"

    response = dana.get("/api/members")

    assert response.status_code == 200
    for one in response.json()["members"]:
        assert one["verified_email"] is None
        assert one["sign_in_methods"] == []
    assert "example.com" not in response.text
