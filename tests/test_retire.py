from __future__ import annotations

import subprocess
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


@pytest.fixture
def dana(team: Team, project: str) -> Session:
    added = team.owner().call("add_member", employee_id="emp-2", name="Dana Dev")
    return Session(team.server, added["personal_token"], project, "billing-api")


RETRIES = {
    "title": "Billing retries three times",
    "summary": "Failed charges are retried three times.",
    "type": "convention",
    "body": "The billing service retries a failed card charge three times before giving up.",
}
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


def promote_superseding(session: Session, memory: dict[str, str], target: str) -> dict[str, Any]:
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level="project")
    resolutions = {s["path"]: ("supersede" if s["path"] == target else "keep_both") for s in first["similar"]}
    result: dict[str, Any] = session.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions=resolutions
    )
    return result


def test_an_author_retires_their_memory_at_once_in_one_commit(team: Team, owner: Session) -> None:
    path = promote_now(owner, RETRIES)

    result = owner.call("retire", path=path)

    subject = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert result == {"status": "retired", "path": path}
    assert owner.call("read", path=path)["status"] == "retired"
    assert subject == "Retire: Billing retries three times"


def test_a_retired_memory_stays_readable_but_leaves_search_recall_and_briefing(owner: Session) -> None:
    path = promote_now(owner, RETRIES)
    owner.call("pin", path=path)

    owner.call("retire", path=path)

    assert owner.call("read", path=path)["title"] == RETRIES["title"]
    assert path not in [r["path"] for r in owner.call("search", query="how many times are charges retried")["results"]]
    assert path not in added_context(owner.prompt("how many times does billing retry a failed charge?"))
    assert path not in added_context(owner.start())


def test_retiring_another_authors_memory_raises_a_retire_challenge(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RETRIES)

    raised = dana.call("retire", path=path)

    assert raised["status"] == "challenge_raised"
    assert owner.call("read", path=path)["status"] == "active"
    assert f"Challenge {raised['challenge_id']} by emp-2: retire it." in added_context(owner.start())


def test_accepting_a_retire_challenge_retires_the_memory(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RETRIES)
    raised = dana.call("retire", path=path)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert owner.call("read", path=path)["status"] == "retired"


def test_rejecting_a_retire_challenge_leaves_the_memory_active(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RETRIES)
    raised = dana.call("retire", path=path)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert owner.call("read", path=path)["status"] == "active"


def test_personal_memory_is_deleted_not_retired(owner: Session) -> None:
    personal = owner.call("remember", **RETRIES)["path"]

    assert "delete_memory" in owner.refusal("retire", path=personal)


def test_a_pin_moves_to_the_memory_that_supersedes_it(owner: Session) -> None:
    old = promote_now(owner, NPM)
    owner.call("pin", path=old)

    new = promote_superseding(owner, PNPM, target=old)["path"]
    briefing = added_context(owner.start())

    assert f"({new})" in briefing
    assert f"({old})" not in briefing


def test_a_pin_moves_when_a_challenge_supersedes_the_pinned_memory(owner: Session, dana: Session) -> None:
    old = promote_now(owner, NPM)
    owner.call("pin", path=old)
    raised = promote_superseding(dana, PNPM, target=old)

    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert f"({accepted['path']})" in added_context(owner.start())


def test_retiring_a_pinned_memory_removes_its_pin(owner: Session, dana: Session) -> None:
    mine = promote_now(owner, RETRIES)
    owner.call("pin", path=mine)
    owner.call("retire", path=mine)

    assert "not pinned" in owner.refusal("unpin", path=mine)
