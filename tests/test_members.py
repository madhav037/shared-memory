from __future__ import annotations

import psycopg

from tests.support import Session, Company


def add(company: Company, member_id: str, name: str) -> Session:
    added = company.owner().call("add_member", member_id=member_id, name=name)
    return Session(company.server, added["personal_token"])


def test_an_added_member_can_use_the_company_memory_with_their_token(company: Company) -> None:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    member = add(company, "emp-2", "Dana Dev").in_project(project)

    saved = member.call("remember", title="Retry twice", summary="s", type="convention", body="b")

    assert member.call("read", path=saved["path"])["author"] == "emp-2"


def test_add_member_shows_the_token_once_and_names_the_member(company: Company) -> None:
    added = company.owner().call("add_member", member_id="emp-2", name="Dana Dev")

    assert added["personal_token"].startswith("smt_")
    assert (added["company"], added["member_id"], added["name"]) == (company.code, "emp-2", "Dana Dev")


def test_a_member_id_can_only_be_added_once(company: Company) -> None:
    company.owner().call("add_member", member_id="emp-2", name="Dana Dev")

    assert "already a member" in company.owner().refusal("add_member", member_id="emp-2", name="Someone Else")


def test_a_removed_members_token_stops_working_but_their_memories_stay(company: Company) -> None:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    member = add(company, "emp-2", "Dana Dev").in_project(project)
    saved = member.call("remember", title="Retry twice", summary="s", type="convention", body="b")

    company.owner().call("remove_member", member_id="emp-2")

    assert "removed from the company" in member.refusal("read", path=saved["path"])
    assert company.owner().in_project(project).call("read", path=saved["path"])["author"] == "emp-2"


def test_reissuing_a_token_revokes_the_old_one(company: Company) -> None:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    old = add(company, "emp-2", "Dana Dev").in_project(project)

    reissued = company.owner().call("reissue_token", member_id="emp-2")
    new = Session(company.server, reissued["personal_token"], project)

    assert "revoked" in old.refusal("remember", title="t", summary="s", type="gotcha", body="b")
    assert new.call("remember", title="t", summary="s", type="gotcha", body="b")["path"]


def test_a_plain_member_cannot_manage_members(company: Company) -> None:
    member = add(company, "emp-2", "Dana Dev")

    for tool, arguments in [
        ("add_member", {"member_id": "emp-3", "name": "Eve"}),
        ("remove_member", {"member_id": "owner-1"}),
        ("reissue_token", {"member_id": "owner-1"}),
    ]:
        assert "owner and its admins" in member.refusal(tool, **arguments)


def test_the_owner_cannot_remove_themselves(company: Company) -> None:
    assert "cannot remove yourself" in company.owner().refusal("remove_member", member_id="owner-1")


def test_managing_an_unknown_member_is_refused(company: Company) -> None:
    assert "No member" in company.owner().refusal("remove_member", member_id="nobody")


def test_every_member_can_use_every_project_in_the_company(company: Company) -> None:
    owners_project = company.owner().call("create_project", name="Billing")["project_id"]
    saved = company.owner().in_project(owners_project).call(
        "remember", title="Owner knowledge", summary="s", type="architecture", body="b"
    )
    member = add(company, "emp-2", "Dana Dev").in_project(owners_project)

    assert member.call("read", path=saved["path"])["title"] == "Owner knowledge"


def test_add_member_accepts_the_company_id_but_only_the_callers_own_company(company: Company) -> None:
    added = company.owner().call("add_member", company=company.code, member_id="emp-2", name="Dana Dev")

    assert added["company"] == company.code
    assert "your own company" in company.owner().refusal(
        "add_member", company="some-other-company", member_id="emp-3", name="Eve"
    )


def test_a_name_must_be_one_line_of_plain_text(company: Company) -> None:
    for name in ["Dana\nDev", "Dana\rDev", "Dana Dev", "Dana\x00Dev", "Dana <dana@x>", "...", "  "]:
        assert "name" in company.owner().refusal("add_member", member_id="emp-2", name=name)


def test_saves_still_land_when_a_stored_name_has_a_line_break(company: Company) -> None:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    member = add(company, "emp-2", "Dana Dev").in_project(project)
    # A name stored before names were checked.
    with psycopg.connect(company.server.settings.database_url, autocommit=True) as conn:
        conn.execute("UPDATE members SET name = %s WHERE member_id = 'emp-2'", ("Dana\n<Dev>",))

    first = member.call("remember", title="Retry twice", summary="s", type="convention", body="b")
    second = company.owner().in_project(project).call("remember", title="Log once", summary="s", type="convention", body="b")

    assert member.call("read", path=first["path"])["author"] == "emp-2"
    assert member.call("read", path=second["path"])["author"] == "owner-1"


def test_a_member_id_with_a_trailing_line_break_is_refused(company: Company) -> None:
    assert "not valid" in company.owner().refusal("add_member", member_id="twin\n", name="Twin")
