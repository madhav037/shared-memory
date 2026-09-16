from __future__ import annotations

from typing import Any

import pytest

from tests.support import Session, Team, added_context


@pytest.fixture
def project(team: Team) -> str:
    project_id: str = team.owner().call("create_project", name="Billing")["project_id"]
    return project_id


@pytest.fixture
def owner(team: Team, project: str) -> Session:
    return team.owner().in_project(project, "billing-api")


def member(team: Team, project: str, employee_id: str, name: str) -> Session:
    added = team.owner().call("add_member", employee_id=employee_id, name=name)
    return Session(team.server, added["personal_token"], project, "billing-api")


@pytest.fixture
def dana(team: Team, project: str) -> Session:
    return member(team, project, "emp-2", "Dana Dev")


@pytest.fixture
def cole(team: Team, project: str) -> Session:
    return member(team, project, "emp-3", "Cole Coder")


NPM = {
    "title": "Use npm for installs",
    "summary": "Packages are installed with npm.",
    "type": "convention",
    "body": "Install dependencies with npm install. Do not use other package managers.",
}
PNPM = {
    "title": "Use pnpm, not npm",
    "summary": "Every package uses pnpm.",
    "type": "convention",
    "body": "We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
}


def promote_now(session: Session, memory: dict[str, str]) -> str:
    result = session.call("promote", path=session.call("remember", **memory)["path"], level="project")
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def challenge(session: Session, memory: dict[str, str], target: str) -> dict[str, Any]:
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level="project")
    resolutions = {s["path"]: ("supersede" if s["path"] == target else "keep_both") for s in first["similar"]}
    result: dict[str, Any] = session.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions=resolutions
    )
    assert result["status"] == "challenge_raised", result
    return {**result, "personal": personal}


def test_any_member_can_decide_a_challenge_after_three_days(team: Team, owner: Session, dana: Session, cole: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    team.server.clock.advance(days=2, hours=23)
    too_early = cole.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    team.server.clock.advance(hours=1)
    decided = cole.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "until it has been open for 3 days" in too_early
    assert decided["status"] == "accepted"


def test_challenges_open_three_days_are_in_every_members_briefing(team: Team, owner: Session, dana: Session, cole: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)
    team.server.clock.advance(days=3)

    assert f"Challenge {raised['challenge_id']} by emp-2" in added_context(cole.start())


def test_challenges_against_a_removed_members_memory_can_be_decided_at_once(team: Team, dana: Session, cole: Session) -> None:
    target = promote_now(dana, NPM)
    raised = challenge(cole, PNPM, target)

    team.owner().call("remove_member", employee_id="emp-2")
    decided = team.owner().in_project(cole.project or "").call(
        "decide_challenge", challenge_id=raised["challenge_id"], decision="reject"
    )

    assert decided["status"] == "rejected"
    assert cole.call("read", path=target)["author"] == "emp-2"


def test_a_removed_members_challenge_stays_open_and_can_be_accepted(team: Team, owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    team.owner().call("remove_member", employee_id="emp-2")
    still_open = owner.call("read", path=target)["open_challenges"]
    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert [c["challenge_id"] for c in still_open] == [raised["challenge_id"]]
    assert owner.call("read", path=accepted["path"])["author"] == "emp-2"


def test_any_member_can_promote_a_removed_members_personal_memory(team: Team, dana: Session, cole: Session) -> None:
    danas = dana.call("remember", **PNPM)["path"]
    team.owner().call("remove_member", employee_id="emp-2")

    result = cole.call("promote", path=danas, level="project")
    promoted = cole.call("read", path=result["path"])

    assert (promoted["author"], promoted["promoted_by"], promoted["level"]) == ("emp-2", "emp-3", "project")


def test_an_active_members_personal_memory_still_cannot_be_promoted_by_others(dana: Session, cole: Session) -> None:
    danas = dana.call("remember", **PNPM)["path"]

    assert "your own personal memory" in cole.refusal("promote", path=danas, level="project")


def test_promoted_by_is_kept_when_promoting_a_removed_members_memory_raises_a_challenge(
    team: Team, owner: Session, dana: Session, cole: Session
) -> None:
    target = promote_now(owner, NPM)
    danas = dana.call("remember", **PNPM)["path"]
    team.owner().call("remove_member", employee_id="emp-2")
    first = cole.call("promote", path=danas, level="project")
    raised = cole.call(
        "promote",
        path=danas,
        level="project",
        reference=first["reference"],
        resolutions={s["path"]: ("supersede" if s["path"] == target else "keep_both") for s in first["similar"]},
    )

    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert owner.call("read", path=accepted["path"])["promoted_by"] == "emp-3"
