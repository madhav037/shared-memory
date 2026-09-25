"""The design's success checks (docs/design.md §10.1), with real Claude Code."""

from __future__ import annotations

from pathlib import Path

import pytest

from smoke.support import REPOSITORY, ask, member, promote
from tests.support import Session, Team


@pytest.fixture
def project(team: Team) -> str:
    project_id: str = team.owner().call("create_project", name="Billing")["project_id"]
    return project_id


@pytest.fixture
def olive(team: Team, project: str) -> Session:
    return team.owner().in_project(project, REPOSITORY)


def test_a_promoted_memory_reaches_a_teammates_next_prompt_without_a_search(
    team: Team, project: str, olive: Session, tmp_path: Path
) -> None:
    promote(
        olive,
        title="Staging database resets at 02:17 UTC",
        summary="The staging database is wiped and reseeded every night at 02:17 UTC.",
        body="The staging database is wiped and reseeded every night at 02:17 UTC. Anything you create there is gone "
        "the next morning, so keep test data in fixtures.",
        type="gotcha",
    )
    dana = member(team, project, "emp-2", "Dana Dev")

    run = ask(dana, tmp_path, "What time does the staging database reset each night?")

    (recall,) = run.hooks_for("UserPromptSubmit")
    assert "02:17" in recall.output
    assert "02:17" in run.answer
    assert run.memory_tools_used() == []


def test_a_new_members_first_session_answers_which_package_manager_from_the_briefing(
    team: Team, project: str, olive: Session, tmp_path: Path
) -> None:
    path = promote(
        olive,
        title="Use pnpm, not npm",
        summary="Every package in billing is managed with pnpm; npm creates a second lockfile that CI rejects.",
        body="We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
    )
    olive.call("pin", path=path)
    nia = member(team, project, "emp-3", "Nia New")

    run = ask(nia, tmp_path, "Which package manager do we use?")

    (briefing,) = run.hooks_for("SessionStart")
    assert "Use pnpm, not npm" in briefing.output
    assert "pnpm" in run.answer.lower()


def test_the_prompt_hook_adds_under_one_second(team: Team, project: str, olive: Session, tmp_path: Path) -> None:
    promote(
        olive,
        title="Errors are returned, never thrown",
        summary="Billing services return Result values for expected errors instead of throwing.",
        body="Expected failures (validation, not found, duplicates) are returned as Result values. Throw only for bugs.",
    )
    dana = member(team, project, "emp-2", "Dana Dev")

    run = ask(
        dana,
        tmp_path,
        "Reply with just the word OK.",
        "How should a billing service report a validation error? One sentence.",
        "Reply with just the word DONE.",
    )

    seconds = [hook.seconds for hook in run.hooks_for("UserPromptSubmit")]
    assert len(seconds) == 3
    assert max(seconds) < 1.0, seconds
