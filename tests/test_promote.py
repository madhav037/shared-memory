from __future__ import annotations

import subprocess
from typing import Any

import pytest

from tests.support import Session, Team


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


PNPM = {
    "title": "Use pnpm, not npm",
    "summary": "Every package uses pnpm.",
    "type": "convention",
    "body": "We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
}
NPM = {
    "title": "Use npm for installs",
    "summary": "Packages are installed with npm.",
    "type": "convention",
    "body": "Install dependencies with npm install. Do not use other package managers.",
}
CENTS = {
    "title": "Money amounts",
    "summary": "Money is integer cents.",
    "type": "convention",
    "body": "All money amounts are stored as integer cents, never floats.",
}


def remember(session: Session, memory: dict[str, str], **extra: Any) -> str:
    path: str = session.call("remember", **memory, **extra)["path"]
    return path


def promoted(session: Session, memory: dict[str, str], level: str = "project") -> str:
    result = session.call("promote", path=remember(session, memory), level=level)
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def test_a_memory_with_nothing_similar_is_promoted_into_project_memory_at_once(owner: Session) -> None:
    personal = remember(owner, CENTS)

    result = owner.call("promote", path=personal, level="project")
    memory = owner.call("read", path=result["path"])

    assert result["status"] == "promoted"
    assert (memory["level"], memory["author"], memory["title"]) == ("project", "owner-1", "Money amounts")
    assert "/shared/conventions/" in result["path"]
    assert "no memory" in owner.refusal("read", path=personal)


def test_team_memory_is_visible_from_every_project(team: Team, owner: Session) -> None:
    path = promoted(owner, CENTS, level="team")
    other_project = team.owner().call("create_project", name="Payments")["project_id"]

    results = team.owner().in_project(other_project).call("search", query="how are money amounts stored")["results"]

    assert path.startswith("team/conventions/")
    assert (results[0]["path"], results[0]["level"]) == (path, "team")


def test_similar_memories_are_returned_before_anything_changes(owner: Session, dana: Session) -> None:
    existing = promoted(dana, NPM)
    personal = remember(owner, PNPM)

    result = owner.call("promote", path=personal, level="project")

    assert result["status"] == "similar_memories"
    assert result["reference"]
    assert [
        {key: similar[key] for key in ("path", "level", "author", "title", "summary", "body")}
        for similar in result["similar"]
    ] == [
        {
            "path": existing,
            "level": "project",
            "author": "emp-2",
            "title": NPM["title"],
            "summary": NPM["summary"],
            "body": NPM["body"],
        }
    ]
    assert owner.call("read", path=personal)["level"] == "personal"


def test_keep_both_completes_the_promotion(owner: Session, dana: Session) -> None:
    existing = promoted(dana, NPM)
    personal = remember(owner, PNPM)
    first = owner.call("promote", path=personal, level="project")

    result = owner.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "keep_both"}
    )

    assert result["status"] == "promoted"
    assert owner.call("read", path=result["path"])["level"] == "project"
    assert owner.call("read", path=existing)["status"] == "active"


def test_cancel_leaves_the_memory_personal(owner: Session, dana: Session) -> None:
    existing = promoted(dana, NPM)
    personal = remember(owner, PNPM)
    first = owner.call("promote", path=personal, level="project")

    result = owner.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "cancel"}
    )

    assert result == {"status": "cancelled", "path": personal}
    assert owner.call("read", path=personal)["level"] == "personal"


def test_every_similar_memory_needs_a_resolution(owner: Session, dana: Session) -> None:
    promoted(dana, NPM)
    personal = remember(owner, PNPM)
    first = owner.call("promote", path=personal, level="project")

    refusal = owner.refusal("promote", path=personal, level="project", reference=first["reference"], resolutions={})

    assert "resolution for every similar memory" in refusal


def test_an_unknown_promotion_reference_is_refused(owner: Session) -> None:
    personal = remember(owner, PNPM)

    assert "reference" in owner.refusal("promote", path=personal, level="project", reference="nope", resolutions={})


def test_promoting_another_members_personal_memory_is_refused(owner: Session, dana: Session) -> None:
    danas = remember(dana, CENTS)

    assert "your own personal memory" in owner.refusal("promote", path=danas, level="project")


def test_promotion_keeps_the_topic_and_is_one_commit(team: Team, owner: Session) -> None:
    personal = remember(owner, CENTS, topic="Money")
    result = owner.call("promote", path=personal, level="project")

    changed = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "show", "--name-status", "--format=%s", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert result["path"].endswith("/shared/conventions/money/money-amounts.md")
    assert changed.startswith("Promote: Money amounts")
    assert f"{team.code}/{personal}" in changed
    assert f"{team.code}/{result['path']}" in changed


def test_promoted_memory_can_no_longer_be_edited_or_deleted(owner: Session) -> None:
    path = promoted(owner, CENTS)

    assert "only edit your own personal memory" in owner.refusal("edit_memory", path=path, body="changed")
    assert "only delete your own personal memory" in owner.refusal("delete_memory", path=path)


def test_promoted_memory_shows_up_in_search_as_project_memory(owner: Session) -> None:
    path = promoted(owner, CENTS)

    first = owner.call("search", query="how are money amounts stored")["results"][0]

    assert (first["path"], first["level"], first["label"]) == (path, "project", "project memory")
