from __future__ import annotations

from tests.support import Session, Team


def add(team: Team, employee_id: str, name: str) -> Session:
    added = team.owner().call("add_member", employee_id=employee_id, name=name)
    return Session(team.server, added["personal_token"])


def test_an_added_member_can_use_the_team_memory_with_their_token(team: Team) -> None:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    member = add(team, "emp-2", "Dana Dev").in_project(project)

    saved = member.call("remember", title="Retry twice", summary="s", type="convention", body="b")

    assert member.call("read", path=saved["path"])["author"] == "emp-2"


def test_add_member_shows_the_token_once_and_names_the_member(team: Team) -> None:
    added = team.owner().call("add_member", employee_id="emp-2", name="Dana Dev")

    assert added["personal_token"].startswith("smt_")
    assert (added["team"], added["employee_id"], added["name"]) == (team.code, "emp-2", "Dana Dev")


def test_an_employee_id_can_only_be_added_once(team: Team) -> None:
    team.owner().call("add_member", employee_id="emp-2", name="Dana Dev")

    assert "already a member" in team.owner().refusal("add_member", employee_id="emp-2", name="Someone Else")


def test_a_removed_members_token_stops_working_but_their_memories_stay(team: Team) -> None:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    member = add(team, "emp-2", "Dana Dev").in_project(project)
    saved = member.call("remember", title="Retry twice", summary="s", type="convention", body="b")

    team.owner().call("remove_member", employee_id="emp-2")

    assert "removed from the team" in member.refusal("read", path=saved["path"])
    assert team.owner().in_project(project).call("read", path=saved["path"])["author"] == "emp-2"


def test_reissuing_a_token_revokes_the_old_one(team: Team) -> None:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    old = add(team, "emp-2", "Dana Dev").in_project(project)

    reissued = team.owner().call("reissue_token", employee_id="emp-2")
    new = Session(team.server, reissued["personal_token"], project)

    assert "revoked" in old.refusal("remember", title="t", summary="s", type="gotcha", body="b")
    assert new.call("remember", title="t", summary="s", type="gotcha", body="b")["path"]


def test_a_plain_member_cannot_manage_members(team: Team) -> None:
    member = add(team, "emp-2", "Dana Dev")

    for tool, arguments in [
        ("add_member", {"employee_id": "emp-3", "name": "Eve"}),
        ("remove_member", {"employee_id": "owner-1"}),
        ("reissue_token", {"employee_id": "owner-1"}),
    ]:
        assert "owner and its admins" in member.refusal(tool, **arguments)


def test_the_owner_cannot_remove_themselves(team: Team) -> None:
    assert "cannot remove yourself" in team.owner().refusal("remove_member", employee_id="owner-1")


def test_managing_an_unknown_member_is_refused(team: Team) -> None:
    assert "No member" in team.owner().refusal("remove_member", employee_id="nobody")


def test_every_member_can_use_every_project_in_the_team(team: Team) -> None:
    owners_project = team.owner().call("create_project", name="Billing")["project_id"]
    saved = team.owner().in_project(owners_project).call(
        "remember", title="Owner knowledge", summary="s", type="architecture", body="b"
    )
    member = add(team, "emp-2", "Dana Dev").in_project(owners_project)

    assert member.call("read", path=saved["path"])["title"] == "Owner knowledge"


def test_add_member_accepts_the_team_id_but_only_the_callers_own_team(team: Team) -> None:
    added = team.owner().call("add_member", team=team.code, employee_id="emp-2", name="Dana Dev")

    assert added["team"] == team.code
    assert "your own team" in team.owner().refusal("add_member", team="some-other-team", employee_id="emp-3", name="Eve")
