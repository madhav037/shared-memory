from __future__ import annotations

import subprocess

from tests.support import NPM, PNPM, Session, Team, added_context, promote_now, promote_superseding


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
