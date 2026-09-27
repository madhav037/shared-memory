"""Running the team from the console: members, admins and ownership."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, ToolRefused, add, signed_in_owner


def members(client: ConsoleClient) -> list[dict[str, Any]]:
    response = client.get("/api/members")
    assert response.status_code == 200, response.text
    listed: list[dict[str, Any]] = response.json()["members"]
    return listed


def test_an_admin_sees_everyone_with_their_role_and_github_account(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_owner(console, signed_out, "olive-members-one", 601)

    add(signed_out, "emp-2", "Dana Dev", "dana-members-one")

    assert members(signed_out) == [
        {
            "member_id": "E1001",
            "name": "Olive Owner",
            "role": "owner",
            "github_login": "olive-members-one",
            "removed": False,
        },
        {
            "member_id": "emp-2",
            "name": "Dana Dev",
            "role": "member",
            "github_login": "dana-members-one",
            "removed": False,
        },
    ]


def test_adding_a_member_shows_their_token_once(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-members-two", 602)

    added = add(signed_out, "emp-2", "Dana Dev")

    assert added["member_id"] == "emp-2"
    assert added["personal_token"].startswith("smt_")
    Session(console.server, added["personal_token"]).call("create_project", name="Dana's check")
    assert added["personal_token"] not in str(members(signed_out))


def test_removing_a_member_ends_their_sessions_and_their_token(console: Console, signed_out: ConsoleClient) -> None:
    team, _ = console.a_team("olive-members-three")
    console.github.as_(603, "olive-members-three")
    signed_out.sign_in()
    added = add(signed_out, "emp-2", "Dana Dev", "dana-members-three")
    dana = console.client()
    console.github.as_(604, "dana-members-three")
    dana.sign_in()
    assert dana.status()["signed_in"] is True

    signed_out.post("/api/members/emp-2/remove")

    assert dana.status()["signed_in"] is False
    assert [one["removed"] for one in members(signed_out) if one["member_id"] == "emp-2"] == [True]
    try:
        Session(console.server, added["personal_token"]).call("create_project", name="After removal")
        raise AssertionError("the removed member's token still works")
    except ToolRefused as refused:
        assert "removed" in str(refused)
    dana.close()


def test_an_admin_corrects_a_name_and_a_github_account(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-members-four", 605)
    add(signed_out, "emp-2", "Dana Dev", "dana-members-four")

    signed_out.post_json("/api/members/emp-2/change", {"name": "Dana Developer", "github": "dana-renamed-four"})

    corrected = [one for one in members(signed_out) if one["member_id"] == "emp-2"]
    assert corrected == [
        {
            "member_id": "emp-2",
            "name": "Dana Developer",
            "role": "member",
            "github_login": "dana-renamed-four",
            "removed": False,
        }
    ]


def test_the_owner_grants_admin_and_takes_it_away(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-members-five", 606)
    add(signed_out, "emp-2", "Dana Dev")

    signed_out.post_json("/api/members/emp-2/admin", {"admin": True})
    granted = [one["role"] for one in members(signed_out) if one["member_id"] == "emp-2"]
    signed_out.post_json("/api/members/emp-2/admin", {"admin": False})
    taken_away = [one["role"] for one in members(signed_out) if one["member_id"] == "emp-2"]

    assert granted == ["admin"]
    assert taken_away == ["member"]


def test_an_admin_can_manage_members_but_not_admins(console: Console, signed_out: ConsoleClient) -> None:
    team, _ = console.a_team("olive-members-six")
    console.github.as_(607, "olive-members-six")
    signed_out.sign_in()
    add(signed_out, "emp-2", "Dana Dev", "dana-members-six")
    add(signed_out, "emp-3", "Ash Admin", "ash-members-six")
    signed_out.post_json("/api/members/emp-3/admin", {"admin": True})
    ash = console.client()
    console.github.as_(608, "ash-members-six")
    ash.sign_in()

    added_by_admin = ash.post_json("/api/members", {"member_id": "emp-4", "name": "New Person"})
    removing_a_member = ash.post("/api/members/emp-2/remove")
    removing_the_owner = ash.post("/api/members/E1001/remove")
    granting_admin = ash.post_json("/api/members/emp-2/admin", {"admin": True})

    assert added_by_admin.status_code == 200
    assert removing_a_member.status_code == 200
    assert removing_the_owner.status_code == 403
    assert "owner can't be removed" in removing_the_owner.json()["message"]
    assert granting_admin.status_code == 403
    assert "Only the team's owner can grant admin" in granting_admin.json()["message"]
    ash.close()


def test_only_the_owner_removes_an_admin(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-members-seven", 609)
    add(signed_out, "emp-2", "Ash Admin", "ash-members-seven")
    add(signed_out, "emp-3", "Bo Admin", "bo-members-seven")
    signed_out.post_json("/api/members/emp-2/admin", {"admin": True})
    signed_out.post_json("/api/members/emp-3/admin", {"admin": True})
    ash = console.client()
    console.github.as_(610, "ash-members-seven")
    ash.sign_in()

    admin_removing_admin = ash.post("/api/members/emp-3/remove")
    owner_removing_admin = signed_out.post("/api/members/emp-3/remove")

    assert admin_removing_admin.status_code == 403
    assert "Only the team's owner can remove an admin" in admin_removing_admin.json()["message"]
    assert owner_removing_admin.status_code == 200
    ash.close()


def test_ownership_is_handed_over(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-members-eight", 611)
    add(signed_out, "emp-2", "Dana Dev", "dana-members-eight")

    signed_out.post("/api/members/emp-2/ownership")

    roles = {one["member_id"]: one["role"] for one in members(signed_out)}
    assert roles == {"E1001": "admin", "emp-2": "owner"}
    assert signed_out.status()["member"]["role"] == "admin"


def test_a_plain_member_cannot_run_the_team(console: Console, signed_out: ConsoleClient) -> None:
    team, _ = console.a_team("olive-members-nine")
    console.github.as_(612, "olive-members-nine")
    signed_out.sign_in()
    add(signed_out, "emp-2", "Dana Dev", "dana-members-nine")
    dana = console.client()
    console.github.as_(613, "dana-members-nine")
    dana.sign_in()

    adding = dana.post_json("/api/members", {"member_id": "emp-9", "name": "Nine"})
    removing = dana.post("/api/members/E1001/remove")

    assert adding.status_code == 403
    assert removing.status_code == 403
    assert "owner and its admins" in adding.json()["message"]
    dana.close()


def test_every_change_to_the_team_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-members-ten", 614)

    add(signed_out, "emp-2", "Dana Dev", "dana-members-ten")
    signed_out.post_json("/api/members/emp-2/admin", {"admin": True})
    signed_out.post_json("/api/members/emp-2/change", {"name": "Dana Developer"})
    signed_out.post("/api/members/emp-2/remove")

    log = signed_out.get("/api/audit").json()["events"]
    assert [event["kind"] for event in log][:5] == [
        "member_removed",
        "member_changed",
        "admin_granted",
        "token_issued",
        "member_added",
    ]
    assert {event["target"] for event in log if event["kind"] != "signed_in"} == {"emp-2"}


def test_an_admin_can_use_the_owners_memory_tools_in_claude(console: Console, signed_out: ConsoleClient) -> None:
    _, owner_token = console.a_team("olive-members-eleven")
    console.github.as_(615, "olive-members-eleven")
    signed_out.sign_in()
    added = add(signed_out, "emp-2", "Ash Admin")
    signed_out.post_json("/api/members/emp-2/admin", {"admin": True})
    ash = Session(console.server, added["personal_token"])

    invited = ash.call("add_member", member_id="emp-3", name="New Person", github="new-person-eleven")

    assert invited["member_id"] == "emp-3"
    assert "owner" in ash.refusal("remove_member", member_id="E1001")
