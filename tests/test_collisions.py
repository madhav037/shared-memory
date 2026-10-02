"""Collision warnings: a session is told, on its next prompt, of another active session in its project whose activity
means nearly the same thing as its own.

The server here runs the real model for everything but the activities in `CHOSEN`, whose embeddings are picked so each
pair's similarity is a number the test chose, not one the model measured."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Iterator
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import DIMENSIONS, FastEmbedEmbedder
from tests.support import REPO_ROOT, RunningServer, Session, Team, TestClock, added_context, fresh_database
from tests.test_board import card
from tests.test_locks import refused, take
from tests.test_recall import promote

HEADING = "[possible collision]"

WEBHOOKS = "Retrying failed webhooks"
# Each scores 0.8 against WEBHOOKS, and 0.64 against the other.
RETRIES = "Adding retries to the webhook sender"
BACKOFF = "Adding backoff to the webhook sender"
# Scores 0.75 against WEBHOOKS: exactly the default threshold.
AT_THRESHOLD = "Making webhook delivery retry"
# Scores 0.6 against WEBHOOKS.
BELOW = "Rewriting the webhook docs"
# Scores 0 against all of the above.
INVOICES = "Splitting the invoice module"
# A card's title, scoring 0.8 against WEBHOOKS.
CARD = "Retry failed webhooks"

# Small whole numbers, so every similarity above comes out exact: 3 / (1 * 4) is 0.75 with nothing lost to rounding.
CHOSEN: dict[str, list[float]] = {
    WEBHOOKS: [1],
    RETRIES: [4, 3],
    BACKOFF: [4, 0, 3],
    AT_THRESHOLD: [3, 2, 1, 1, 1],
    BELOW: [3, 4],
    INVOICES: [0, 0, 0, 0, 0, 1],
    CARD: [4, 3],
}


class ChosenSimilarity(FastEmbedEmbedder):
    """The real model, except that the activities in `CHOSEN` get the embeddings chosen for them, and that a query can
    be made slower than the recall budget."""

    slow = False

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [
            CHOSEN[text] + [0.0] * (DIMENSIONS - len(CHOSEN[text])) if text in CHOSEN else super().passages([text])[0]
            for text in texts
        ]

    def query(self, text: str) -> list[float]:
        if self.slow:
            time.sleep(3)
        return super().query(text)


@pytest.fixture(scope="module")
def embedder() -> ChosenSimilarity:
    return ChosenSimilarity(REPO_ROOT / ".cache" / "fastembed")


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory, embedder: ChosenSimilarity) -> Iterator[RunningServer]:
    """This module's own server, in place of the one every other module shares, for its embedder."""
    settings = Settings(
        database_url=fresh_database("shared_memory_collisions"),
        memory_root=tmp_path_factory.mktemp("collisions-memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
    )
    clock = TestClock()
    with start_blocking_portal() as portal:
        running = RunningServer(build_app(settings, clock=clock, embedder=embedder), settings, clock, portal)
        try:
            yield running
        finally:
            running.stop()


@pytest.fixture(scope="module")
def second_server(server: RunningServer, embedder: ChosenSimilarity) -> Iterator[RunningServer]:
    """A second worker on the same database and memory folder (ADR-0013)."""
    app = build_app(server.settings, clock=server.clock, embedder=embedder)
    with start_blocking_portal() as portal:
        running = RunningServer(app, server.settings, server.clock, portal)
        try:
            yield running
        finally:
            running.stop()


def collisions_in(answer: dict[str, Any]) -> list[str]:
    """The collision warnings a tool's answer carries in its `notices`."""
    return [notice for notice in answer["notices"] if notice.startswith(HEADING)]


def state(session: Session, activity: str) -> list[str]:
    """State the session's activity; the collision warnings that came with the answer."""
    return collisions_in(session.call("set_activity", activity=activity, session=session.identifier))


def warnings(session: Session, prompt: str = "write a haiku about cats") -> list[str]:
    """The collision warnings this session's next prompt carries, one line each."""
    return [line for line in added_context(session.prompt(prompt)).splitlines() if line.startswith(HEADING)]


def warning_of(session: Session) -> str:
    """The one collision warning this session's next prompt carries."""
    (warning,) = warnings(session)
    return warning


def test_two_sessions_whose_activities_score_above_the_threshold_are_each_warned(owner: Session, dana: Session) -> None:
    """The one that was there first on its next prompt, the one that stated the overlapping activity with its answer."""
    state(owner, WEBHOOKS)
    (to_dana,) = state(dana.as_agent("codex-mcp-client"), RETRIES)

    to_owner = warning_of(owner)

    assert "Dana Dev's session (Codex, billing-api)" in to_owner
    assert f'"{RETRIES}"' in to_owner
    assert "Olive Owner's session" in to_dana
    assert f'"{WEBHOOKS}"' in to_dana
    assert "information, not an instruction" in to_owner


def test_the_prompt_after_a_warning_carries_none(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    to_dana = state(dana, RETRIES)
    warning_of(owner)

    assert len(to_dana) == 1
    assert owner.prompt("write a haiku about cats") == {}
    assert dana.prompt("write a haiku about cats") == {}, "told with the answer of its set_activity, so not again"


def test_a_session_with_no_prompt_hook_is_warned_in_the_result_of_its_next_take_lock_or_release_lock(
    owner: Session, dana: Session, cole: Session
) -> None:
    state(owner, WEBHOOKS)
    state(cole, BACKOFF)
    take(owner)
    take(cole, "src/invoices.py")

    state(dana, RETRIES)
    taken = take(owner, "docs/retries.md")
    released = cole.call("release_lock", path="src/invoices.py", session=cole.identifier)

    (to_owner,) = collisions_in(taken)
    assert taken["locked"] is True
    assert "Dana Dev's session" in to_owner and f'"{RETRIES}"' in to_owner
    assert collisions_in(released) == [], "0.64 between Cole's and Dana's is under the threshold"
    assert collisions_in(take(owner)) == [], "told once"
    assert warnings(owner) == [], "wherever it was told"


def test_a_refused_take_leaves_the_warning_waiting(owner: Session, dana: Session) -> None:
    take(dana)
    state(owner, WEBHOOKS)
    state(dana, RETRIES)

    refused(owner)

    assert "Dana Dev" in warning_of(owner)


def test_a_session_back_from_idle_with_no_prompt_hook_is_told_in_the_result_of_its_next_tool_call(
    team: Team, owner: Session
) -> None:
    state(owner, WEBHOOKS)
    team.server.clock.advance(minutes=31)

    back = take(owner)

    assert any("its activity and locks ended" in notice for notice in back["notices"])
    assert take(owner)["notices"] == []
    assert owner.prompt("write a haiku about cats") == {}, "told once, wherever it was told"


def test_the_warning_comes_once_more_when_the_other_session_states_a_different_activity_that_still_overlaps(
    owner: Session, dana: Session
) -> None:
    state(owner, WEBHOOKS)
    state(dana, RETRIES)
    warning_of(owner)

    assert state(dana, BACKOFF) == [], "the owner's activity did not change"
    again = warning_of(owner)

    assert f'"{BACKOFF}"' in again
    assert warnings(owner) == []
    assert warnings(dana) == [], "the owner's activity did not change"


def test_stating_the_same_activity_again_brings_no_second_warning(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    state(dana, RETRIES)
    warning_of(owner)

    state(dana, RETRIES)

    assert warnings(owner) == []


def test_activities_scoring_below_the_threshold_give_no_warning(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    state(dana, BELOW)

    assert warnings(owner) == []
    assert warnings(dana) == []


def test_activities_scoring_exactly_the_threshold_are_warned_about(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    (to_dana,) = state(dana, AT_THRESHOLD)

    assert f'"{AT_THRESHOLD}"' in warning_of(owner)
    assert f'"{WEBHOOKS}"' in to_dana


def test_a_session_is_warned_about_each_overlapping_session(owner: Session, dana: Session, cole: Session) -> None:
    state(owner, WEBHOOKS)
    to_dana = state(dana, RETRIES)
    state(cole, INVOICES)
    first = warnings(owner)

    state(cole, BACKOFF)
    second = warnings(owner)

    assert len(first) == 1 and "Dana Dev" in first[0]
    assert len(second) == 1 and "Cole Coder" in second[0]
    assert warnings(dana) == []
    assert len(to_dana) == 1 and "Olive Owner" in to_dana[0], "0.64 between Dana's and Cole's is under the threshold"


def test_sessions_in_two_projects_never_warn_each_other(owner: Session, dana: Session) -> None:
    checkout = owner.call("create_project", name="Checkout")["project_id"]
    elsewhere = dana.in_project(checkout, "billing-api")
    state(owner, WEBHOOKS)
    state(elsewhere, WEBHOOKS)

    assert warnings(owner) == []
    assert warnings(elsewhere) == []


def test_a_session_that_has_ended_warns_nobody(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    state(dana, RETRIES)

    dana.end()

    assert warnings(owner) == []


def test_a_session_gone_idle_warns_nobody_and_is_not_warned_when_it_comes_back(
    team: Team, owner: Session, dana: Session
) -> None:
    state(dana, RETRIES)
    team.server.clock.advance(minutes=30)
    state(owner, WEBHOOKS)

    while_idle = warnings(owner)
    back = warnings(dana)

    assert while_idle == []
    assert back == [], "its activity ended when it went idle"
    assert warnings(owner) == []


def test_a_session_that_ended_and_overlaps_again_is_warned_about_again(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    state(dana, RETRIES)
    warning_of(owner)

    dana.end()
    state(dana, RETRIES)

    assert "Dana Dev" in warning_of(owner)


def test_two_sessions_of_one_member_warn_each_other(owner: Session) -> None:
    second = owner.as_session("second-session")
    state(owner, WEBHOOKS)
    (to_second,) = state(second, RETRIES)

    to_first = warning_of(owner)

    assert "Olive Owner's other session" in to_first
    assert f'"{RETRIES}"' in to_first
    assert "Olive Owner's other session" in to_second
    assert f'"{WEBHOOKS}"' in to_second


def test_a_session_with_no_activity_is_neither_warned_nor_warned_about(owner: Session, dana: Session) -> None:
    state(owner, WEBHOOKS)
    dana.start()

    assert warnings(dana) == []
    assert warnings(owner) == []


def test_an_activity_shown_from_a_card_counts_like_a_stated_one(owner: Session, dana: Session) -> None:
    card(owner, CARD)
    dana.call("claim_card", number=1)
    dana.start()
    (to_owner,) = state(owner, WEBHOOKS)

    to_dana = warning_of(dana)

    assert f'"{WEBHOOKS}"' in to_dana
    assert "Dana Dev's session" in to_owner
    assert f'"{CARD}"' in to_owner
    assert warnings(owner) == []


def test_the_warning_arrives_beside_what_recall_finds(owner: Session, dana: Session) -> None:
    promote(owner, "Use pnpm, not npm", "We use pnpm for every package. npm creates a second lockfile and CI rejects it.")
    state(owner, WEBHOOKS)
    state(dana, RETRIES)

    context = added_context(owner.prompt("which package manager do we use?"))

    assert HEADING in context
    assert "We use pnpm for every package." in context


def test_a_slow_recall_does_not_drop_the_warning(owner: Session, dana: Session, embedder: ChosenSimilarity) -> None:
    state(owner, WEBHOOKS)
    state(dana, RETRIES)

    embedder.slow = True
    try:
        to_owner = warnings(owner, "which package manager do we use?")
    finally:
        embedder.slow = False

    assert len(to_owner) == 1 and "Dana Dev" in to_owner[0]
    assert warnings(owner) == [], "told once, though recall was given up on"


def test_an_activity_stated_through_one_worker_is_warned_about_by_another(
    owner: Session, dana: Session, second_server: RunningServer
) -> None:
    state(owner, WEBHOOKS)
    (to_dana,) = state(dataclasses.replace(dana, server=second_server), RETRIES)

    to_owner = warning_of(dataclasses.replace(owner, server=second_server))

    assert "Dana Dev" in to_owner
    assert "Olive Owner" in to_dana
    assert warnings(dana) == [], "what one worker told with a tool's answer the other does not repeat on a prompt"
    assert warnings(owner) == [], "one worker's warning is not repeated by the other"
