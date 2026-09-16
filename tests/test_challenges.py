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
BUN = {
    "title": "Use bun for packages",
    "summary": "Packages are managed with bun.",
    "type": "convention",
    "body": "We install and manage every package with bun because installs are faster than npm.",
}


def promote_now(session: Session, memory: dict[str, str]) -> str:
    result = session.call("promote", path=session.call("remember", **memory)["path"], level="project")
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def challenge(session: Session, memory: dict[str, str], target: str) -> dict[str, Any]:
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level="project")
    assert first["status"] == "similar_memories", first
    resolutions = {s["path"]: ("supersede" if s["path"] == target else "keep_both") for s in first["similar"]}
    result: dict[str, Any] = session.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions=resolutions
    )
    return {**result, "personal": personal}


def test_superseding_another_authors_memory_raises_a_challenge(owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)

    raised = challenge(dana, PNPM, target)
    pending = dana.call("read", path=raised["personal"])
    challenged = dana.call("read", path=target)

    assert raised["status"] == "challenge_raised"
    assert pending["level"] == "personal"
    assert pending["pending"] == [{"challenge_id": raised["challenge_id"], "kind": "supersede", "replaces": target}]
    assert challenged["status"] == "active"
    assert [c["challenge_id"] for c in challenged["open_challenges"]] == [raised["challenge_id"]]


def test_the_author_sees_the_challenge_in_their_briefing_and_next_prompt(owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    briefing = added_context(owner.start())
    prompt = added_context(owner.prompt("write a haiku about cats"))

    for context in (briefing, prompt):
        assert f"Challenge {raised['challenge_id']} by emp-2" in context
        assert target in context
        assert "decide_challenge" in context


def test_accepting_a_challenge_promotes_the_challenging_memory_over_the_old_one(owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    new = owner.call("read", path=accepted["path"])
    old = owner.call("read", path=target)

    assert accepted["status"] == "accepted"
    assert (new["level"], new["author"], new["replaces"], new["pending"]) == ("project", "emp-2", target, [])
    assert (old["status"], old["superseded_by"], old["open_challenges"]) == ("superseded", accepted["path"], [])


def test_rejecting_a_challenge_leaves_the_memory_personal(owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")
    kept = dana.call("read", path=raised["personal"])

    assert (kept["level"], kept["pending"]) == ("personal", [])
    assert owner.call("read", path=target)["status"] == "active"
    assert "was rejected" in added_context(dana.prompt("write a haiku about cats"))


def test_only_the_challenged_memorys_author_can_decide(owner: Session, dana: Session, cole: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    refusal = cole.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "Only owner-1" in refusal


def test_challenges_against_one_memory_are_decided_together(owner: Session, dana: Session, cole: Session) -> None:
    target = promote_now(owner, NPM)
    danas = challenge(dana, PNPM, target)
    coles = challenge(cole, BUN, target)

    briefing = added_context(owner.start())
    owner.call("decide_challenge", challenge_id=danas["challenge_id"], decision="accept")
    coles_view = cole.call("read", path=coles["personal"])

    assert f"Challenge {danas['challenge_id']} by emp-2" in briefing
    assert f"Challenge {coles['challenge_id']} by emp-3" in briefing
    assert coles_view["pending"] == []
    assert "closed" in added_context(cole.prompt("write a haiku about cats"))
    assert owner.call("read", path=target)["open_challenges"] == []


def test_a_memory_waiting_on_a_challenge_cannot_be_promoted_again(owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    assert "waiting on challenge" in dana.refusal("promote", path=raised["personal"], level="project")
