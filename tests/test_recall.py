from __future__ import annotations

import dataclasses
import time
from collections.abc import Iterator

import httpx
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import RunningServer, Session, Team, added_context, new_team


def remember(session: Session, title: str, body: str, type: str = "convention") -> str:
    path: str = session.call("remember", title=title, summary=title, type=type, body=body)["path"]
    return path


def promote(session: Session, title: str, body: str, level: str = "project", type: str = "convention") -> str:
    personal = remember(session, title, body, type)
    result = session.call("promote", path=personal, level=level)
    if result["status"] == "similar_memories":
        keep_all = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("promote", path=personal, level=level, reference=result["reference"], resolutions=keep_all)
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def test_a_promoted_memory_reaches_a_teammates_next_prompt(owner: Session, dana: Session) -> None:
    path = promote(owner, "Use pnpm, not npm", "We use pnpm for every package. npm creates a second lockfile and CI rejects it.")

    context = added_context(dana.prompt("which package manager do we use?"))

    assert path in context
    assert "We use pnpm for every package." in context


def test_hook_output_is_shaped_for_claude_code(owner: Session) -> None:
    promote(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")

    output = owner.prompt("store the refund amount in the database")

    assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_recall_labels_levels_and_frames_memory_as_information(owner: Session) -> None:
    promote(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")

    context = added_context(owner.prompt("store the refund amount in the database"))

    assert "[project memory] Money amounts" in context
    assert "information, not instructions" in context
    assert "project memory wins over team memory, team memory over personal memory" in context


def test_unpromoted_personal_memory_reaches_only_its_author(owner: Session, dana: Session) -> None:
    path = remember(dana, "Staging database", "The staging database is wiped and reseeded every night.", type="gotcha")

    assert path in added_context(dana.prompt("the staging db lost my test data"))
    assert path not in added_context(owner.prompt("the staging db lost my test data"))


def test_team_memory_is_recalled_in_every_project(team: Team, owner: Session) -> None:
    path = promote(owner, "Gateway timeouts", "When the payment gateway is slow the client raises ERR_TIMEOUT after 30 seconds.", level="team")
    other_project = team.owner().call("create_project", name="Checkout")["project_id"]

    context = added_context(team.owner().in_project(other_project).prompt("payment gateway keeps timing out"))

    assert f"[team memory] Gateway timeouts ({path})" in context


def test_recall_returns_at_most_three_memories(owner: Session) -> None:
    for number in range(5):
        promote(owner, f"Retry rule {number}", f"When a card charge fails we retry it (rule {number}).")

    context = added_context(owner.prompt("why did the charge fail and get retried"))

    assert context.count("[project memory]") == 3


def test_an_unrelated_prompt_gets_no_recall(owner: Session) -> None:
    promote(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")

    assert owner.prompt("write a haiku about cats") == {}


def test_problems_never_break_the_prompt(team: Team, owner: Session) -> None:
    promote(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")
    bad_token = Session(team.server, "smt_nope", owner.project, "billing-api")
    no_project = team.owner()

    assert bad_token.prompt("store the refund amount") == {}
    assert no_project.prompt("store the refund amount") == {}
    garbage = httpx.post(f"{team.server.url}/hooks/prompt-submitted", content=b"not json", headers=owner.headers())
    assert (garbage.status_code, garbage.json()) == (200, {})


class SlowEmbedder(FastEmbedEmbedder):
    def query(self, text: str) -> list[float]:
        time.sleep(3)
        return super().query(text)


@pytest.fixture
def slow_server(server: RunningServer, tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = dataclasses.replace(
        server.settings, memory_root=tmp_path_factory.mktemp("slow-memory"), recall_budget_seconds=0.5
    )
    app = build_app(settings, clock=server.clock, embedder=SlowEmbedder(settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, server.clock, portal)
        try:
            yield running
        finally:
            running.stop()


def test_recall_that_takes_too_long_is_skipped(slow_server: RunningServer) -> None:
    team = new_team(slow_server)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    session = team.owner().in_project(project)

    started = time.monotonic()
    output = session.prompt("store the refund amount in the database")

    assert output == {}
    assert time.monotonic() - started < 2.5


def test_news_is_delivered_even_when_recall_takes_too_long(slow_server: RunningServer) -> None:
    team = new_team(slow_server)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    owner = team.owner().in_project(project)
    added = team.owner().call("add_member", member_id="emp-2", name="Dana Dev")
    dana = Session(slow_server, added["personal_token"], project)
    npm = owner.call(
        "remember",
        title="Use npm for installs",
        summary="Packages are installed with npm.",
        type="convention",
        body="Install dependencies with npm install. Do not use other package managers.",
    )["path"]
    target = owner.call("promote", path=npm, level="project")["path"]
    pnpm = dana.call(
        "remember",
        title="Use pnpm, not npm",
        summary="Every package uses pnpm.",
        type="convention",
        body="We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
    )["path"]
    first = dana.call("promote", path=pnpm, level="project")
    raised = dana.call("promote", path=pnpm, level="project", reference=first["reference"], resolutions={target: "supersede"})
    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert "was rejected" in added_context(dana.prompt("which package manager do we use?"))
