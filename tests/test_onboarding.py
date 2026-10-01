"""Onboarding: the steps a session is given to import a member's existing setup, and promote naming the member who
wrote an imported memory as its author."""

from __future__ import annotations

from typing import Any

from tests.support import (
    NPM,
    PNPM,
    REPO_ROOT,
    Console,
    ConsoleClient,
    Session,
    Team,
    added_context,
    promote_now,
    signed_in_owner,
)

CENTS = {
    "title": "Money amounts",
    "summary": "Money is integer cents.",
    "type": "convention",
    "body": "All money amounts are stored as integer cents, never floats.",
}
SOURCE = "billing-api:CLAUDE.md"


def imported(session: Session, memory: dict[str, str] = CENTS) -> str:
    """A memory the session's member has imported, still in their personal memory."""
    path: str = session.call("remember", **memory)["path"]
    return path


def promoted_for(session: Session, author: str, memory: dict[str, str] = CENTS, level: str = "project") -> str:
    result = session.call("promote", path=imported(session, memory), level=level, author=author, imported_from=SOURCE)
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


# The steps, and where a session finds them


def test_the_onboarding_steps_are_served_as_a_tool_and_as_a_prompt(owner: Session) -> None:
    steps = owner.call("onboard")

    assert owner.run_prompt("onboard") == steps
    for needed in ("git blame", "remember", "promote", "author", "imported_from", "secret", "ten"):
        assert needed in steps, needed


def test_onboarding_needs_a_connected_repository(team: Team) -> None:
    assert "isn't connected to a project" in team.owner().refusal("onboard")
    assert "isn't connected to a project" in team.owner().run_prompt("onboard")


def test_an_agent_learns_on_connecting_that_onboarding_starts_only_when_the_member_asks(team: Team) -> None:
    instructions, tools = team.owner().on_connecting()

    assert "onboard" in instructions
    assert "only when the member asks" in tools["onboard"]


def test_the_skills_point_at_the_served_steps_instead_of_repeating_them(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing", repository="billing-api")
    every_agents = next(f for f in created["files"] if f["path"] == ".agents/skills/shared-memory/SKILL.md")
    claude_codes = (REPO_ROOT / "plugin" / "skills" / "onboard" / "SKILL.md").read_text(encoding="utf-8")

    for skill in (every_agents["contents"], claude_codes):
        assert "`onboard`" in skill
        assert "git blame" not in skill


# Promote naming the author of an imported memory


def test_a_member_named_as_author_becomes_the_author_and_the_importer_and_source_are_recorded(
    owner: Session, dana: Session
) -> None:
    memory = owner.call("read", path=promoted_for(owner, "emp-2"))

    assert (memory["level"], memory["author"]) == ("project", "emp-2")
    assert (memory["imported_by"], memory["imported_from"]) == ("owner-1", SOURCE)


def test_the_author_can_be_named_by_their_github_username(team: Team, owner: Session) -> None:
    team.owner().call("add_member", member_id="emp-7", name="Gita Hub", github="Gita-Hub")

    memory = owner.call("read", path=promoted_for(owner, "@gita-hub", level="team"))

    assert (memory["level"], memory["author"], memory["imported_by"]) == ("team", "emp-7", "owner-1")


def test_someone_who_is_not_a_member_cannot_be_named_as_author(team: Team, owner: Session, dana: Session) -> None:
    personal = imported(owner)
    team.owner().call("remove_member", member_id="emp-2")

    unknown = owner.refusal("promote", path=personal, level="project", author="emp-99", imported_from=SOURCE)
    no_account = owner.refusal("promote", path=personal, level="project", author="@nobody", imported_from=SOURCE)
    removed = owner.refusal("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)

    assert "No member with member ID 'emp-99'" in unknown
    assert "@nobody" in no_account and "without author" in no_account
    assert "No member with member ID 'emp-2'" in removed
    assert owner.call("read", path=personal)["level"] == "personal"


def test_a_member_outside_a_restricted_project_cannot_be_named_as_author(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards-closed", 7801)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")
    closed = signed_out.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    assert closed.status_code == 200, closed.text
    in_project = owner.in_project(project, "billing-api")

    for level in ("project", "team"):
        refusal = in_project.refusal(
            "promote", path=imported(in_project), level=level, author="emp-2", imported_from=SOURCE
        )
        assert "can't reach project" in refusal, level


def test_an_author_is_named_only_with_the_source_and_never_oneself(owner: Session, dana: Session) -> None:
    personal = imported(owner)

    assert "imported_from" in owner.refusal("promote", path=personal, level="project", author="emp-2")
    assert "author" in owner.refusal("promote", path=personal, level="project", imported_from=SOURCE)
    assert "already its author" in owner.refusal(
        "promote", path=personal, level="project", author="owner-1", imported_from=SOURCE
    )
    assert "repository:path" in owner.refusal(
        "promote", path=personal, level="project", author="emp-2", imported_from="CLAUDE.md\nand more"
    )


def test_the_author_is_told_in_their_next_briefing(owner: Session, dana: Session) -> None:
    path = promoted_for(owner, "emp-2")

    told = added_context(dana.start())

    assert "owner-1 promoted a memory in your name" in told
    assert path in told and SOURCE in told and "Money amounts" in told
    assert "in your name" not in added_context(dana.start())
    assert "in your name" not in added_context(owner.start())


def test_the_named_author_retires_the_memory_as_any_author_does(owner: Session, dana: Session) -> None:
    path = promoted_for(owner, "emp-2")

    by_the_importer = owner.call("retire", path=path)
    by_the_author = dana.call("retire", path=path)

    assert by_the_importer["status"] == "challenge_raised"
    assert by_the_author == {"status": "retired", "path": path}


def test_the_similar_memory_check_still_runs_and_the_author_holds_through_it(owner: Session, dana: Session) -> None:
    existing = promote_now(owner, NPM)
    personal = imported(owner, PNPM)

    first = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)
    while_it_waits = owner.call("read", path=personal)
    result = owner.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "keep_both"}
    )

    assert first["status"] == "similar_memories"
    assert (while_it_waits["level"], while_it_waits["author"]) == ("personal", "owner-1")
    memory = owner.call("read", path=result["path"])
    assert (memory["author"], memory["imported_by"], memory["imported_from"]) == ("emp-2", "owner-1", SOURCE)


def test_the_author_holds_when_the_promotion_waits_on_a_challenge(owner: Session, dana: Session, cole: Session) -> None:
    existing = promote_now(cole, NPM)
    personal = imported(owner, PNPM)
    first = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)
    raised = owner.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "supersede"}
    )

    accepted = cole.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    memory = owner.call("read", path=accepted["path"])
    assert (memory["author"], memory["imported_by"], memory["replaces"]) == ("emp-2", "owner-1", existing)
    assert "owner-1 promoted a memory in your name" in added_context(dana.start())


def test_a_cancelled_promotion_leaves_no_author_behind_for_the_next_one(owner: Session, dana: Session) -> None:
    existing = promote_now(owner, NPM)
    personal = imported(owner, PNPM)
    first = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)
    owner.call("promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "cancel"})

    again = owner.call("promote", path=personal, level="project")
    result = owner.call(
        "promote", path=personal, level="project", reference=again["reference"], resolutions={existing: "keep_both"}
    )

    memory = owner.call("read", path=result["path"])
    assert (memory["author"], memory["imported_by"], memory["imported_from"]) == ("owner-1", None, None)


def test_the_audit_log_shows_the_author_and_the_importer(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards", 7802)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")
    in_project = owner.in_project(project, "billing-api")

    path = promoted_for(in_project, "emp-2")

    response = signed_out.get(f"/api/audit?project={project}&kind=memory_promoted")
    assert response.status_code == 200, response.text
    (event,) = response.json()["events"]
    detail: dict[str, Any] = event["detail"]
    assert (event["actor"], event["target"]) == ("E1001", path)
    assert (detail["author"], detail["imported_by"], detail["imported_from"]) == ("emp-2", "E1001", SOURCE)


def test_the_console_still_reads_an_imported_memory(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards-reads", 7803)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")

    path = promoted_for(owner.in_project(project, "billing-api"), "emp-2")

    response = signed_out.get(f"/api/memory?path={path}")
    assert response.status_code == 200, response.text
    assert (response.json()["author"], response.json()["author_name"]) == ("emp-2", "Dana Dev")
    assert "imported_by: E1001" in response.json()["source"]
