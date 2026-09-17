from __future__ import annotations

import subprocess

from tests.support import Session, Team


def test_a_member_reads_back_a_memory_they_remembered(team: Team) -> None:
    owner = team.owner()
    project = owner.call("create_project", name="Billing")
    session = owner.in_project(project["project_id"], "billing-api")

    saved = session.call(
        "remember",
        title="Use pnpm, not npm",
        summary="Every package in billing uses pnpm.",
        type="convention",
        body="We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
    )
    memory = session.call("read", path=saved["path"])

    assert memory["title"] == "Use pnpm, not npm"
    assert memory["summary"] == "Every package in billing uses pnpm."
    assert memory["type"] == "convention"
    assert memory["author"] == "owner-1"
    assert memory["status"] == "active"
    assert memory["level"] == "personal"
    assert memory["body"] == "We use pnpm for every package. npm creates a second lockfile and CI rejects it."


def test_a_call_without_a_personal_token_is_refused(team: Team) -> None:
    anonymous = Session(team.server, token=None)

    assert "No personal token" in anonymous.refusal("create_project", name="Billing")


def test_a_call_with_an_unknown_personal_token_is_refused(team: Team) -> None:
    stranger = Session(team.server, token="smt_not-a-real-token")

    assert "not recognised" in stranger.refusal("create_project", name="Billing")


def test_each_save_is_one_commit_credited_to_the_member(team: Team) -> None:
    owner = team.owner()
    project = owner.call("create_project", name="Billing")["project_id"]
    session = owner.in_project(project)

    session.call("remember", title="Staging resets nightly", summary="s", type="gotcha", body="At 02:00 UTC.")

    log = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "log", "-1", "--format=%an|%ae|%s", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    header, *files = [line for line in log.splitlines() if line]
    assert header == "Olive Owner|owner-1@members.shared-memory.invalid|Remember: Staging resets nightly"
    assert f"{team.code}/projects/{project}/people/owner-1/gotchas/staging-resets-nightly.md" in files


def test_create_project_gives_the_settings_a_repository_needs(team: Team) -> None:
    created = team.owner().call("create_project", name="Billing API", repository="billing-web")

    assert created["project_id"].startswith("billing-api-")
    assert created["settings"]["env"] == {
        "SHARED_MEMORY_PROJECT": created["project_id"],
        "SHARED_MEMORY_REPOSITORY": "billing-web",
    }


def test_memory_tools_need_a_project(team: Team) -> None:
    refusal = team.owner().refusal("remember", title="t", summary="s", type="gotcha", body="b")

    assert "isn't connected to a project" in refusal


def test_a_project_from_another_team_is_refused(team: Team) -> None:
    from tests.support import new_team

    other = new_team(team.server)
    foreign_project = other.owner().call("create_project", name="Theirs")["project_id"]

    refusal = team.owner().in_project(foreign_project).refusal("read", path="team/conventions/x.md")

    assert "not a project in your team" in refusal
