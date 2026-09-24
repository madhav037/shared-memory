from __future__ import annotations

import subprocess
from typing import Any

from tests.support import Session, Team, added_context


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
JSON_LOGS = {
    "title": "Log in JSON",
    "summary": "All services log JSON.",
    "type": "convention",
    "body": "Every service writes structured JSON logs to stdout.",
}
PLAIN_LOGS = {
    "title": "Billing logs plain text",
    "summary": "The billing service logs plain text.",
    "type": "convention",
    "body": "The old billing service writes plain text logs to stdout, not JSON.",
}


def promote_now(session: Session, memory: dict[str, str], level: str = "project") -> str:
    personal = session.call("remember", **memory)["path"]
    result = session.call("promote", path=personal, level=level)
    if result["status"] == "similar_memories":
        keep = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("promote", path=personal, level=level, reference=result["reference"], resolutions=keep)
    path: str = result["path"]
    return path


def promote_superseding(session: Session, memory: dict[str, str], target: str, level: str = "project") -> dict[str, Any]:
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level=level)
    assert first["status"] == "similar_memories", first
    resolutions = {similar["path"]: ("supersede" if similar["path"] == target else "keep_both") for similar in first["similar"]}
    result: dict[str, Any] = session.call(
        "promote", path=personal, level=level, reference=first["reference"], resolutions=resolutions
    )
    return result


def test_superseding_your_own_memory_replaces_it(owner: Session) -> None:
    old = promote_now(owner, NPM)

    result = promote_superseding(owner, PNPM, target=old)
    new = owner.call("read", path=result["path"])
    replaced = owner.call("read", path=old)

    assert result["status"] == "promoted"
    assert (new["status"], new["replaces"]) == ("active", old)
    assert (replaced["status"], replaced["superseded_by"]) == ("superseded", result["path"])


def test_superseding_is_a_single_commit(team: Team, owner: Session) -> None:
    old = promote_now(owner, NPM)

    result = promote_superseding(owner, PNPM, target=old)

    changed = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "show", "--name-only", "--format=%s", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert changed.startswith("Promote: Use pnpm, not npm")
    assert f"{team.code}/{old}" in changed
    assert f"{team.code}/{result['path']}" in changed


def test_a_superseded_memory_leaves_search_and_recall(owner: Session) -> None:
    old = promote_now(owner, NPM)
    promote_superseding(owner, PNPM, target=old)

    found = [result["path"] for result in owner.call("search", query="install dependencies with npm")["results"]]

    assert old not in found
    assert old not in added_context(owner.prompt("which package manager do we use for installs?"))


def test_a_project_memory_contradicting_team_memory_becomes_an_exception(team: Team, owner: Session, dana: Session) -> None:
    team_memory = promote_now(dana, JSON_LOGS, level="team")

    result = promote_superseding(owner, PLAIN_LOGS, target=team_memory)
    exception = owner.call("read", path=result["path"])
    other_project = team.owner().call("create_project", name="Checkout")["project_id"]

    assert (exception["level"], exception["exception_to"]) == ("project", team_memory)
    assert owner.call("read", path=team_memory)["status"] == "active"
    assert team_memory in added_context(team.owner().in_project(other_project).prompt("how should services log?"))


def test_recall_marks_an_exception_so_claude_applies_it_in_that_project(owner: Session, dana: Session) -> None:
    team_memory = promote_now(dana, JSON_LOGS, level="team")
    promote_superseding(owner, PLAIN_LOGS, target=team_memory)

    context = added_context(owner.prompt("how does the billing service write its logs?"))

    assert f"exception to {team_memory}" in context
