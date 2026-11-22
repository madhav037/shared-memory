"""An admin adds a member by email or GitHub login (#680, ADR-0034): whichever sign-in method first proves the added
email is recognised as that member, and an email an admin typed stays unverified until its holder proves it."""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any

import httpx
import psycopg
import pytest

from tests.support import Console, ConsoleClient, Session, ToolRefused, sign_in_error

NOT_LINKED = "isn't linked to a member. Ask an admin to link it to you."
REMOVED = "You have been removed from this company"

_numbers = itertools.count(8100)
_domains = itertools.count(1)
DOMAIN = "t0.example.com"


@pytest.fixture(autouse=True)
def _a_domain_of_its_own() -> None:
    """Every test's emails live under a domain of its own: the matcher looks across the server's companies."""
    global DOMAIN
    DOMAIN = f"t{next(_domains)}.example.com"


def mail(local: str) -> str:
    return f"{local}@{DOMAIN}"


def gh(label: str) -> tuple[str, int]:
    """A GitHub login and account number no other test in this module uses."""
    number = next(_numbers)
    return f"{label}-ae{number}", number


def entry(email: str, primary: bool = True, verified: bool = True) -> dict[str, Any]:
    return {"email": email, "primary": primary, "verified": verified, "visibility": None}


def sign_in(console: Console, login: str, account: int, *emails: dict[str, Any]) -> tuple[ConsoleClient, httpx.Response]:
    """Someone signs in with this GitHub account, which lists these emails."""
    client = console.client()
    console.github.as_(account, login)
    console.github.has_emails(*emails)
    return client, client.sign_in()


def a_company(console: Console, label: str, *emails: dict[str, Any]) -> ConsoleClient:
    """A company whose owner is signed in."""
    login, account = gh(label)
    console.a_company(login)
    client, landed = sign_in(console, login, account, *emails)
    assert client.status()["signed_in"] is True, sign_in_error(landed)
    return client


def new(client: ConsoleClient, member_id: str, **fields: Any) -> httpx.Response:
    return client.post_json("/api/members", {"member_id": member_id, "name": f"Name {member_id}", **fields})


def added(client: ConsoleClient, member_id: str, **fields: Any) -> dict[str, Any]:
    response = new(client, member_id, **fields)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def changed(client: ConsoleClient, member_id: str, **fields: Any) -> httpx.Response:
    return client.post_json(f"/api/members/{member_id}/change", fields)


def listed(client: ConsoleClient) -> dict[str, dict[str, Any]]:
    response = client.get("/api/members")
    assert response.status_code == 200, response.text
    return {one["member_id"]: one for one in response.json()["members"]}


def refused_by(client: ConsoleClient, landed: httpx.Response) -> str:
    assert client.status()["signed_in"] is False, "the sign-in was let in"
    return sign_in_error(landed)


def audit_text(client: ConsoleClient) -> str:
    response = client.get("/api/audit?limit=200")
    assert response.status_code == 200, response.text
    return response.text


def an_admin(console: Console, owner: ConsoleClient, member_id: str, label: str) -> ConsoleClient:
    login, account = gh(label)
    added(owner, member_id, github=login)
    assert owner.post_json(f"/api/members/{member_id}/admin", {"admin": True}).status_code == 200
    client, landed = sign_in(console, login, account)
    assert client.status()["signed_in"] is True, sign_in_error(landed)
    return client


# -- the nine criteria ---------------------------------------------------------------------------------------------


def test_criterion_one_field_in_the_console_accepts_an_email_or_a_github_login(console: Console) -> None:
    owner = a_company(console, "olive-c1")

    by_email = added(owner, "emp-2", email=mail("Dana"))
    by_login = added(owner, "emp-3", github="@dana-c1")

    assert by_email["personal_token"].startswith("smt_") and by_login["personal_token"].startswith("smt_")
    seen = listed(owner)
    assert (seen["emp-2"]["added_email"], seen["emp-2"]["github_login"]) == (mail("Dana"), None)
    assert (seen["emp-3"]["added_email"], seen["emp-3"]["github_login"]) == (None, "dana-c1")


def test_criterion_the_add_member_tool_accepts_an_email(console: Console) -> None:
    owner = a_company(console, "olive-c2")
    token = added(owner, "emp-2", github=gh("ash-c2")[0])["personal_token"]
    owner.post_json("/api/members/emp-2/admin", {"admin": True})

    result = Session(console.server, token).call("add_member", member_id="emp-3", name="New Person", email=mail("new"))

    assert result["member_id"] == "emp-3"
    assert listed(owner)["emp-3"]["added_email"] == mail("new")
    with pytest.raises(ToolRefused) as both:
        Session(console.server, token).call(
            "add_member", member_id="emp-4", name="Both", email=mail("both"), github="both-c2"
        )
    assert "not both" in str(both.value)


def test_criterion_an_added_email_is_shown_as_unverified_until_its_holder_proves_it(console: Console) -> None:
    owner = a_company(console, "olive-c3")
    added(owner, "emp-2", email=mail("dana"))

    before = listed(owner)["emp-2"]
    login, account = gh("dana-c3")
    dana, _ = sign_in(console, login, account, entry(mail("dana")))
    after = listed(owner)["emp-2"]

    assert (before["added_email"], before["verified_email"]) == (mail("dana"), None)
    assert dana.status()["signed_in"] is True
    assert (after["added_email"], after["verified_email"]) == (None, mail("dana"))


def test_criterion_adding_an_email_another_member_holds_in_any_case_is_refused(console: Console) -> None:
    owner = a_company(console, "olive-c4", entry(mail("Olive")))
    added(owner, "emp-2", email=mail("Dana"))

    by_verified = new(owner, "emp-3", email=mail("OLIVE"))
    by_added = new(owner, "emp-4", email=mail("dana"))

    assert by_verified.status_code == 403 and by_added.status_code == 403
    assert "already" in by_added.json()["message"]
    assert "example.com" not in by_added.json()["message"].lower()
    assert set(listed(owner)) == {"E1001", "emp-2"}


def test_criterion_a_github_sign_in_with_the_added_email_verified_links_that_account_to_that_member(
    console: Console,
) -> None:
    owner = a_company(console, "olive-c5")
    added(owner, "emp-2", email=mail("dana"))
    login, account = gh("dana-c5")

    dana, landed = sign_in(console, login, account, entry(mail("Dana")))

    assert dana.status()["member"]["member_id"] == "emp-2", sign_in_error(landed)
    row = listed(owner)["emp-2"]
    assert (row["github_login"], row["verified_email"], row["added_email"]) == (login, mail("Dana"), None)
    dana.sign_out()
    again, _ = sign_in(console, login, account)  # the account now signs in by its key, with no email at all
    assert again.status()["member"]["member_id"] == "emp-2"
    assert "linked" in audit_text(owner)


def test_criterion_a_github_account_that_was_not_added_with_an_email_nobody_holds_is_refused_and_audited(
    console: Console,
) -> None:
    owner = a_company(console, "olive-c6")
    login, account = gh("stranger-c6")

    stranger, landed = sign_in(console, login, account, entry(mail("nobody")))

    assert NOT_LINKED in refused_by(stranger, landed)
    log = owner.get("/api/audit?kind=sign_in_refused").json()["events"]
    assert log[0]["actor"] == f"@{login}"
    assert NOT_LINKED in log[0]["detail"]["reason"]
    assert "example.com" not in audit_text(owner)


@pytest.mark.parametrize("how", ["added", "verified"])
def test_criterion_a_removed_member_is_not_let_back_in_by_a_matching_email(console: Console, how: str) -> None:
    owner = a_company(console, f"olive-c7-{how}")
    if how == "added":
        added(owner, "emp-2", email=mail("dana"))
    else:
        added(owner, "emp-2", github=(held := gh(f"dana-c7-{how}"))[0])
        sign_in(console, held[0], held[1], entry(mail("dana")))
    assert owner.post("/api/members/emp-2/remove").status_code == 200
    before = listed(owner)["emp-2"]
    login, account = gh(f"newcomer-c7-{how}")

    newcomer, landed = sign_in(console, login, account, entry(mail("dana")))

    assert REMOVED in refused_by(newcomer, landed)
    assert listed(owner)["emp-2"] == before
    assert listed(owner)["emp-2"]["github_login"] != login


def test_criterion_only_the_owner_can_change_an_admins_email(console: Console) -> None:
    owner = a_company(console, "olive-c8")
    ash = an_admin(console, owner, "emp-2", "ash-c8")
    other = an_admin(console, owner, "emp-3", "bo-c8")
    added(owner, "emp-4", github=gh("dana-c8")[0])

    by_admin = changed(ash, "emp-3", email=mail("new"), name="Renamed")
    own_row = changed(ash, "emp-2", email=mail("ash"))
    owners = changed(ash, "E1001", email=mail("takeover"))
    by_owner = changed(owner, "emp-3", email=mail("bo"))
    by_admin_on_member = changed(ash, "emp-4", email=mail("dana"))

    assert by_admin.status_code == 403 and "owner" in by_admin.json()["message"]
    assert owners.status_code == 403 and "owner" in owners.json()["message"]
    assert (own_row.status_code, by_owner.status_code, by_admin_on_member.status_code) == (200, 200, 200)
    seen = listed(owner)
    assert seen["emp-3"]["name"] == "Name emp-3"  # the refused request changed nothing, not even the name
    assert seen["emp-3"]["added_email"] == mail("bo")
    assert seen["E1001"]["added_email"] is None
    assert seen["emp-2"]["added_email"] == mail("ash")
    assert other.status()["signed_in"] is True


def test_criterion_setup_accepts_the_owners_email_in_place_of_a_github_login(console: Console) -> None:
    code = "acme-c9"
    printed = console.server.run_cli(
        "setup", "--company", code, "--owner-member-id", "E1001", "--owner-name", "Olive Owner",
        "--owner-email", mail("olive"),
    )  # fmt: skip
    assert "Owner personal token" in printed
    login, account = gh("olive-c9")

    owner, landed = sign_in(console, login, account, entry(mail("olive")))

    assert owner.status()["member"]["member_id"] == "E1001", sign_in_error(landed)
    seen = listed(owner)["E1001"]
    assert (seen["github_login"], seen["verified_email"], seen["added_email"]) == (login, mail("olive"), None)
    with pytest.raises(SystemExit):
        console.server.run_cli(
            "setup", "--company", "acme-c9b", "--owner-member-id", "E1001", "--owner-name", "Olive Owner",
            "--owner-email", mail("olive"), "--owner-github", "olive",
        )  # fmt: skip


# -- an email never gets around a GitHub link ----------------------------------------------------------------------


def test_an_account_relinked_to_another_login_cannot_sign_back_in_with_its_email(console: Console) -> None:
    owner = a_company(console, "olive-unlink-one")
    login, account = gh("dana-unlink-one")
    added(owner, "emp-2", github=login)
    sign_in(console, login, account, entry(mail("dana")))
    assert listed(owner)["emp-2"]["verified_email"] == mail("dana")

    assert changed(owner, "emp-2", github=gh("dana-new-one")[0]).status_code == 200
    old, landed = sign_in(console, login, account, entry(mail("dana")))

    assert listed(owner)["emp-2"]["verified_email"] is None
    assert NOT_LINKED in refused_by(old, landed)


def test_an_account_cleared_to_empty_by_an_admin_cannot_sign_back_in_with_its_email(console: Console) -> None:
    owner = a_company(console, "olive-unlink-two")
    login, account = gh("dana-unlink-two")
    added(owner, "emp-2", github=login)
    sign_in(console, login, account, entry(mail("dana")))

    assert changed(owner, "emp-2", github="").status_code == 200
    old, landed = sign_in(console, login, account, entry(mail("dana")))

    row = listed(owner)["emp-2"]
    assert (row["github_login"], row["verified_email"]) == (None, None)
    assert NOT_LINKED in refused_by(old, landed)


def test_an_account_relinked_by_the_command_line_cannot_sign_back_in_with_its_email(console: Console) -> None:
    login, account = gh("olive-unlink-three")
    company, _ = console.a_company(login)
    owner, _ = sign_in(console, login, account)
    login, account = gh("dana-unlink-three")
    added(owner, "emp-2", github=login)
    sign_in(console, login, account, entry(mail("dana")))

    console.server.run_cli("link-github", "--company", company, "--member-id", "emp-2", "--github", gh("dana-new-three")[0])
    old, landed = sign_in(console, login, account, entry(mail("dana")))

    assert listed(owner)["emp-2"]["verified_email"] is None
    assert NOT_LINKED in refused_by(old, landed)


def test_the_same_login_again_keeps_the_verified_email(console: Console) -> None:
    owner = a_company(console, "olive-unlink-four")
    login, account = gh("dana-unlink-four")
    added(owner, "emp-2", github=login)
    sign_in(console, login, account, entry(mail("dana")))

    assert changed(owner, "emp-2", github=login.upper()).status_code == 200

    assert listed(owner)["emp-2"]["verified_email"] == mail("dana")


@pytest.mark.parametrize("how", ["pending", "bound", "verified"])
def test_an_email_match_never_replaces_a_github_link(console: Console, how: str) -> None:
    owner = a_company(console, f"olive-nolink-{how}")
    login, account = gh(f"dana-nolink-{how}")
    added(owner, "emp-2", github=login)
    if how == "bound":
        sign_in(console, login, account)
    if how == "verified":
        sign_in(console, login, account, entry(mail("dana")))
    else:
        assert changed(owner, "emp-2", email=mail("dana")).status_code == 200
    before = listed(owner)["emp-2"]
    thief, thief_account = gh(f"thief-nolink-{how}")

    stranger, landed = sign_in(console, thief, thief_account, entry(mail("dana")))

    assert NOT_LINKED in refused_by(stranger, landed)
    assert listed(owner)["emp-2"] == before
    assert listed(owner)["emp-2"]["github_login"] == login


@pytest.mark.parametrize(
    "emails",
    [[entry(mail("dana"), verified=False)], [entry(mail("dana"), primary=False)]],
    ids=["unverified", "not-primary"],
)
def test_an_unverified_or_non_primary_github_email_links_nobody(console: Console, emails: list[dict[str, Any]]) -> None:
    owner = a_company(console, "olive-weak")
    added(owner, "emp-2", email=mail("dana"))
    login, account = gh("stranger-weak")

    stranger, landed = sign_in(console, login, account, *emails)

    assert NOT_LINKED in refused_by(stranger, landed)
    row = listed(owner)["emp-2"]
    assert (row["github_login"], row["added_email"], row["verified_email"]) == (None, mail("dana"), None)


def test_two_members_in_two_companies_holding_one_email_link_nobody(console: Console) -> None:
    first = a_company(console, "olive-two-companies-a")
    second = a_company(console, "olive-two-companies-b")
    added(first, "emp-2", email=mail("dana"))
    added(second, "emp-2", email=mail("dana"))
    login, account = gh("dana-two-companies")

    dana, landed = sign_in(console, login, account, entry(mail("dana")))

    assert "more than one company" in refused_by(dana, landed)
    assert listed(first)["emp-2"]["github_login"] is None
    assert listed(second)["emp-2"]["github_login"] is None


# -- the key wins -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("theirs", ["added", "verified"])
def test_the_key_wins_when_the_email_belongs_to_another_member_and_neither_moves(console: Console, theirs: str) -> None:
    owner = a_company(console, f"olive-key-{theirs}")
    if theirs == "added":
        added(owner, "emp-3", email=mail("shared"))
    else:
        other = gh(f"eli-key-{theirs}")
        added(owner, "emp-3", github=other[0])
        sign_in(console, other[0], other[1], entry(mail("shared")))
    before = listed(owner)["emp-3"]
    login, account = gh(f"dana-key-{theirs}")
    added(owner, "emp-2", github=login)

    dana, landed = sign_in(console, login, account, entry(mail("Shared")))

    assert dana.status()["member"]["member_id"] == "emp-2", sign_in_error(landed)
    assert listed(owner)["emp-3"] == before
    assert listed(owner)["emp-2"]["verified_email"] is None
    assert listed(owner)["emp-2"]["added_email"] is None


def test_a_member_with_an_added_email_keeps_only_a_proven_email_equal_to_it(console: Console) -> None:
    owner = a_company(console, "olive-keep")
    login, account = gh("dana-keep")
    added(owner, "emp-2", github=login)
    changed(owner, "emp-2", email=mail("dana"))

    sign_in(console, login, account, entry(mail("other")))
    after_other = listed(owner)["emp-2"]
    sign_in(console, login, account, entry(mail("DANA")))
    after_own = listed(owner)["emp-2"]

    assert (after_other["added_email"], after_other["verified_email"]) == (mail("dana"), None)
    assert (after_own["added_email"], after_own["verified_email"]) == (None, mail("DANA"))


def test_a_proven_email_cannot_take_one_that_is_another_members_added_email(console: Console) -> None:
    owner = a_company(console, "olive-take")
    added(owner, "emp-3", email=mail("held"))
    login, account = gh("dana-take")
    added(owner, "emp-2", github=login)

    sign_in(console, login, account, entry(mail("held")))

    assert listed(owner)["emp-2"]["verified_email"] is None
    assert listed(owner)["emp-3"]["added_email"] == mail("held")


# -- changing an email ----------------------------------------------------------------------------------------------


def test_changing_an_email_sets_it_unverified_and_empty_clears_both(console: Console) -> None:
    owner = a_company(console, "olive-change")
    login, account = gh("dana-change")
    added(owner, "emp-2", github=login)
    sign_in(console, login, account, entry(mail("dana")))

    same = changed(owner, "emp-2", email=mail("DANA"))
    after_same = listed(owner)["emp-2"]
    assert changed(owner, "emp-2", email=mail("new")).status_code == 200
    after_new = listed(owner)["emp-2"]
    assert changed(owner, "emp-2", email="").status_code == 200
    after_empty = listed(owner)["emp-2"]

    assert same.status_code == 200
    assert (after_same["verified_email"], after_same["added_email"]) == (mail("dana"), None)
    assert (after_new["verified_email"], after_new["added_email"]) == (None, mail("new"))
    assert (after_empty["verified_email"], after_empty["added_email"]) == (None, None)


def test_when_a_request_changes_the_github_account_and_the_email_the_email_given_wins(console: Console) -> None:
    owner = a_company(console, "olive-both")
    login, account = gh("dana-both")
    added(owner, "emp-2", github=login)
    sign_in(console, login, account, entry(mail("dana")))

    assert changed(owner, "emp-2", github=gh("dana-both-new")[0], email=mail("dana")).status_code == 200

    row = listed(owner)["emp-2"]
    assert (row["verified_email"], row["added_email"]) == (None, mail("dana"))


def test_an_email_another_member_holds_cannot_be_changed_to(console: Console) -> None:
    owner = a_company(console, "olive-change-taken", entry(mail("olive")))
    added(owner, "emp-2", email=mail("dana"))
    added(owner, "emp-3", github=gh("eli-change-taken")[0])

    on_verified = changed(owner, "emp-3", email=mail("OLIVE"))
    on_added = changed(owner, "emp-3", email=mail("dana"))

    assert on_verified.status_code == 403 and on_added.status_code == 403
    assert listed(owner)["emp-3"]["added_email"] is None


@pytest.mark.parametrize(
    "email",
    [
        "no-at-sign.example.com",
        "two@@example.com",
        "a@b@example.com",
        "@example.com",
        "dana@",
        "dana@nodot",
        "da na@example.com",
        "dana@exa mple.com",
        "dana@example.com extra",
        "dana@exam\x00ple.com",
        "dana@exam	ple.com",
        "x" * 250 + "@example.com",
    ],
)
def test_an_email_that_is_not_one_is_refused_everywhere(console: Console, email: str) -> None:
    owner = a_company(console, "olive-invalid")
    added(owner, "emp-3", github=gh("eli-invalid")[0])

    on_add = new(owner, "emp-2", email=email)
    on_change = changed(owner, "emp-3", email=email)

    assert on_add.status_code in (403, 422), on_add.text
    assert on_change.status_code in (403, 422), on_change.text
    assert set(listed(owner)) == {"E1001", "emp-3"}
    assert listed(owner)["emp-3"]["added_email"] is None


def test_an_add_with_both_an_email_and_a_github_login_is_refused(console: Console) -> None:
    owner = a_company(console, "olive-both-fields")

    response = new(owner, "emp-2", email=mail("dana"), github="dana-both-fields")

    assert response.status_code in (403, 422)
    assert set(listed(owner)) == {"E1001"}


def test_a_removed_members_email_is_still_held(console: Console) -> None:
    owner = a_company(console, "olive-held")
    added(owner, "emp-2", email=mail("dana"))
    owner.post("/api/members/emp-2/remove")

    again = new(owner, "emp-3", email=mail("Dana"))

    assert again.status_code == 403


def test_two_adds_racing_for_one_email_leave_exactly_one_holder(console: Console) -> None:
    owner = a_company(console, "olive-race")
    answers: list[int] = []
    barrier = threading.Barrier(4)

    def add_one(member_id: str) -> None:
        barrier.wait()
        answers.append(new(owner, member_id, email=mail("race")).status_code)

    threads = [threading.Thread(target=add_one, args=(f"emp-{n}",)) for n in range(2, 6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(answers) == [200, 403, 403, 403]
    assert [one["added_email"] for one in listed(owner).values()].count(mail("race")) == 1


# -- privacy ------------------------------------------------------------------------------------------------------------


def test_a_member_who_is_not_an_admin_never_sees_an_added_email(console: Console) -> None:
    owner = a_company(console, "olive-private")
    login, account = gh("dana-private")
    added(owner, "emp-2", github=login)
    added(owner, "emp-3", email=mail("eli"))
    member, _ = sign_in(console, login, account)

    response = member.get("/api/members")

    assert response.status_code == 200
    assert all(one["added_email"] is None for one in response.json()["members"])
    assert "example.com" not in response.text


def test_no_email_is_written_to_the_audit_log_only_that_one_was_given(console: Console) -> None:
    owner = a_company(console, "olive-audit")
    added(owner, "emp-2", email=mail("dana"))
    login, account = gh("eli-audit")
    added(owner, "emp-3", github=login)
    changed(owner, "emp-3", email=mail("eli"))
    dana_login, dana_account = gh("dana-audit-in")
    sign_in(console, dana_login, dana_account, entry(mail("dana")))

    log = owner.get("/api/audit?limit=200").json()["events"]

    assert "example.com" not in audit_text(owner)
    by_kind = {event["kind"]: event for event in log}
    assert by_kind["member_changed"]["detail"]["email"] is True
    assert any(event["kind"] == "member_added" and event["detail"].get("email") is True for event in log)
    assert any(event["kind"] == "signed_in" and event["detail"].get("linked") is True for event in log)


# -- emails are ASCII ---------------------------------------------------------------------------------------------------


def a_pair() -> tuple[str, str]:
    """An ASCII address under a domain of its own, and the address that differs from it by one non-ASCII letter."""
    domain = f"gmail{next(_domains)}.com"
    return f"victim@{domain}", f"victim@{domain.replace('i', chr(0x130), 1)}"


def a_pair_in_the_local_part() -> tuple[str, str]:
    domain = f"site{next(_domains)}.org"
    return f"kevin@{domain}", f"{chr(0x212A)}evin@{domain}"


@pytest.mark.parametrize("pair", [a_pair, a_pair_in_the_local_part], ids=["domain", "local-part"])
@pytest.mark.parametrize("how", ["added", "verified"])
def test_emails_are_ascii_so_a_non_ascii_email_matches_nobody(console: Console, how: str, pair: Any) -> None:
    held, other = pair()
    owner = a_company(console, f"olive-ascii-{how}")
    if how == "added":
        added(owner, "emp-2", email=held)
    else:
        login, account = gh(f"dana-ascii-{how}")
        added(owner, "emp-2", github=login)
        sign_in(console, login, account, entry(held))
        # Only a member with no GitHub linked can be matched by email, so take the link away, as the row would be.
        with psycopg.connect(console.server.settings.database_url, autocommit=True) as conn:
            conn.execute("UPDATE members SET github_login = NULL, github_user_id = NULL WHERE member_id = 'emp-2' AND verified_email = %s", (held,))
    before = listed(owner)["emp-2"]
    thief, thief_account = gh(f"thief-ascii-{how}")

    stranger, landed = sign_in(console, thief, thief_account, entry(other))

    assert NOT_LINKED in refused_by(stranger, landed)
    assert listed(owner)["emp-2"] == before


@pytest.mark.parametrize("pair", [a_pair, a_pair_in_the_local_part], ids=["domain", "local-part"])
def test_emails_are_ascii_so_a_linked_member_proving_one_stores_nothing(console: Console, pair: Any) -> None:
    held, other = pair()
    owner = a_company(console, "olive-ascii-keep")
    login, account = gh("dana-ascii-keep")
    added(owner, "emp-2", github=login)
    changed(owner, "emp-2", email=held)
    login2, account2 = gh("eli-ascii-keep")
    added(owner, "emp-3", github=login2)

    sign_in(console, login, account, entry(other))
    sign_in(console, login2, account2, entry(other))

    assert (listed(owner)["emp-2"]["added_email"], listed(owner)["emp-2"]["verified_email"]) == (held, None)
    assert listed(owner)["emp-3"]["verified_email"] is None


@pytest.mark.parametrize("pair", [a_pair, a_pair_in_the_local_part], ids=["domain", "local-part"])
def test_emails_are_ascii_on_add_change_and_setup(console: Console, pair: Any) -> None:
    _, other = pair()
    owner = a_company(console, "olive-ascii-write")
    added(owner, "emp-3", github=gh("eli-ascii-write")[0])

    on_add = new(owner, "emp-2", email=other)
    on_change = changed(owner, "emp-3", email=other)

    assert on_add.status_code in (403, 422) and on_change.status_code in (403, 422)
    assert set(listed(owner)) == {"E1001", "emp-3"}
    assert listed(owner)["emp-3"]["added_email"] is None
    with pytest.raises(RuntimeError):
        console.server.run_cli(
            "setup", "--company", "acme-ascii", "--owner-member-id", "E1001", "--owner-name", "Olive Owner",
            "--owner-email", other,
        )  # fmt: skip


def test_emails_are_ascii_so_a_stored_non_ascii_value_is_never_matched_by_an_ascii_one(console: Console) -> None:
    held, other = a_pair()
    login, account = gh("olive-ascii-stored")
    company, _ = console.a_company(login)
    owner, _ = sign_in(console, login, account)
    added(owner, "emp-2", email=mail("placeholder"))
    with psycopg.connect(console.server.settings.database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE members SET added_email = %s WHERE member_id = 'emp-2' AND team_id = (SELECT id FROM teams WHERE code = %s)",
            (other, company),
        )
    thief, thief_account = gh("thief-ascii-stored")

    stranger, landed = sign_in(console, thief, thief_account, entry(held))

    assert NOT_LINKED in refused_by(stranger, landed)
    assert listed(owner)["emp-2"]["added_email"] == other


# -- the lookup locks the row ---------------------------------------------------------------------------------------


def _waiting_on_a_lock(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
    ).fetchone()
    return bool(row and row[0] > 0)


@pytest.mark.parametrize("change", ["unlinked", "removed"])
def test_the_lookup_locks_the_row_so_a_sign_in_waits_for_a_change_and_sees_it(console: Console, change: str) -> None:
    login, account = gh(f"olive-lock-{change}")
    company, _ = console.a_company(login)
    owner, _ = sign_in(console, login, account)
    dana, dana_account = gh(f"dana-lock-{change}")
    added(owner, "emp-2", github=dana)
    sign_in(console, dana, dana_account, entry(mail("dana")))
    changes = {
        "unlinked": "github_login = 'moved-on', github_user_id = NULL, verified_email = NULL",
        "removed": "removed_at = now()",
    }
    holder = psycopg.connect(console.server.settings.database_url)
    answers: list[tuple[ConsoleClient, httpx.Response]] = []
    try:
        holder.execute(
            f"UPDATE members SET {changes[change]} WHERE member_id = 'emp-2'"
            " AND team_id = (SELECT id FROM teams WHERE code = %s)",
            (company,),
        )
        thread = threading.Thread(target=lambda: answers.append(sign_in(console, dana, dana_account, entry(mail("dana")))))
        thread.start()
        deadline = time.monotonic() + 30
        while not _waiting_on_a_lock(holder) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _waiting_on_a_lock(holder), "the sign-in did not wait for the row"
        holder.commit()
        thread.join(30)
    finally:
        holder.close()

    client, landed = answers[0]
    assert (NOT_LINKED if change == "unlinked" else REMOVED) in refused_by(client, landed)
    row = listed(owner)["emp-2"]
    assert row["verified_email"] is None if change == "unlinked" else row["removed"] is True
    assert row["github_login"] == ("moved-on" if change == "unlinked" else dana)
