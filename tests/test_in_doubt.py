"""A memory in doubt ranks lower and is marked wherever a session is shown it (#537, spec #502).

Recall and search multiply its score by `in_doubt_penalty`: a down-rank, not a filter. Recall, search, read, the
briefing's pinned memories and the save's similar-memory answer each carry an in-doubt line with the count and the
reasons. Rejecting the doubt restores the rank and drops the mark.

The server here runs the real model for everything but the memories in `CHOSEN` and the query `QUERY`, whose
embeddings are picked so the two rounding memories score the same for it: which one ranks first is then down to doubt
alone. `QUERY` shares no word with them, so search's keyword ranking can't tell them apart either."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import DIMENSIONS, FastEmbedEmbedder
from tests.support import (
    RunningServer,
    Session,
    added_context,
    fresh_database,
    member,
    new_team,
    promote_keeping_both,
)

QUERY = "Which way do we go?"
HALF_UP = {
    "title": "Invoice totals round half up",
    "summary": "Totals are rounded half up.",
    "type": "convention",
    "body": "Totals are rounded half up, to two places.",
}
TO_THE_CENT = {
    "title": "Invoice totals round to the cent",
    "summary": "Totals are rounded to the cent.",
    "type": "convention",
    "body": "Totals are rounded to the cent before tax is added.",
}
BANKERS = {
    "title": "Invoice totals use bankers rounding",
    "summary": "Totals use bankers rounding.",
    "type": "convention",
    "body": "Totals use bankers rounding, half to even.",
}
CHOSEN: dict[str, list[float]] = {
    HALF_UP["title"]: [1],
    TO_THE_CENT["title"]: [1],
    BANKERS["title"]: [1],
    QUERY: [1],
}
TAX_LINE = {"code_reference": "billing-api:src/tax.py:42", "quoted_line": "total = total.quantize(CENT, ROUND_DOWN)"}
LINE = "In doubt: 3 say it misled them; 1 says it contradicts billing-api:src/tax.py:42"


def chosen(text: str) -> list[float] | None:
    """The embedding chosen for a section, by the memory's title on its first line, or for the query."""
    vector = CHOSEN.get(text.split("\n", 1)[0])
    return None if vector is None else vector + [0.0] * (DIMENSIONS - len(vector))


class ChosenSimilarity(FastEmbedEmbedder):
    """The real model, except for the memories and the query in `CHOSEN`."""

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [chosen(text) or super().passages([text])[0] for text in texts]

    def query(self, text: str) -> list[float]:
        return chosen(text) or super().query(text)


@pytest.fixture(scope="module")
def doubt_server(server: RunningServer, tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    """This module's own server and database, for its embedder: a reindex elsewhere rebuilds only its own memory."""
    settings = dataclasses.replace(
        server.settings,
        database_url=fresh_database("shared_memory_in_doubt"),
        memory_root=tmp_path_factory.mktemp("in-doubt-memory"),
    )
    app = build_app(settings, clock=server.clock, embedder=ChosenSimilarity(settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, server.clock, portal)
        try:
            yield running
        finally:
            running.stop()


class Billing:
    """A team with a Billing project, its owner and three members, each with a session in Billing."""

    def __init__(self, server: RunningServer) -> None:
        team = new_team(server)
        self.project = team.owner().call("create_project", name="Billing")["project_id"]
        self.owner = team.owner().in_project(self.project, "billing-api")
        self.dana = member(team, self.project, "emp-2", "Dana Dev")
        self.cole = member(team, self.project, "emp-3", "Cole Coder")
        self.erin = member(team, self.project, "emp-4", "Erin Engineer")

    def doubt(self, path: str) -> int:
        """Three members say the memory misled them, and its author says it contradicts the code."""
        first = self.dana.call("challenge", path=path, reason="misled", reasoning="It rounded the wrong way.")
        self.cole.call("challenge", path=path, reason="misled")
        self.erin.call("challenge", path=path, reason="misled")
        self.owner.call("challenge", path=path, reason="contradicts_code", **TAX_LINE)
        challenge_id: int = first["challenge_id"]
        return challenge_id

    def doubt_once(self, path: str) -> int:
        challenge_id: int = self.dana.call("challenge", path=path, reason="misled")["challenge_id"]
        return challenge_id


@pytest.fixture
def billing(doubt_server: RunningServer) -> Billing:
    return Billing(doubt_server)


def recalled(session: Session, paths: list[str], identifier: str) -> list[str]:
    """The paths among these that a fresh session's recall for `QUERY` names, in the order it names them."""
    context = added_context(session.as_session(identifier).prompt(QUERY))
    found = [path for path in paths if path in context]
    return sorted(found, key=context.index)


def searched(session: Session, paths: list[str]) -> list[str]:
    return [result["path"] for result in session.call("search", query=QUERY)["results"] if result["path"] in paths]


def two_equal(billing: Billing) -> list[str]:
    return [promote_keeping_both(billing.owner, HALF_UP), promote_keeping_both(billing.owner, TO_THE_CENT)]


def test_recall_ranks_a_memory_in_doubt_below_an_equally_scored_memory_that_is_not(billing: Billing) -> None:
    paths = two_equal(billing)
    before = recalled(billing.dana, paths, "before")
    assert len(before) == 2, before

    billing.doubt_once(before[0])

    assert recalled(billing.dana, paths, "after") == before[::-1]


def test_search_ranks_a_memory_in_doubt_below_an_equally_scored_memory_that_is_not(billing: Billing) -> None:
    paths = two_equal(billing)
    before = searched(billing.dana, paths)
    assert len(before) == 2, before

    billing.doubt_once(before[0])

    assert searched(billing.dana, paths) == before[::-1]


def test_recall_shows_the_in_doubt_line_with_the_count_and_reasons(billing: Billing) -> None:
    path = promote_keeping_both(billing.owner, HALF_UP)
    billing.doubt(path)

    context = added_context(billing.dana.as_session("marked").prompt(QUERY))

    assert path in context
    assert LINE in context


def test_search_shows_the_in_doubt_line_with_the_count_and_reasons(billing: Billing) -> None:
    doubted, sound = two_equal(billing)
    billing.doubt(doubted)

    results = {result["path"]: result for result in billing.dana.call("search", query=QUERY)["results"]}

    assert results[doubted]["in_doubt"] == LINE
    assert "in_doubt" not in results[sound]


def test_read_shows_the_in_doubt_line_with_the_count_and_reasons(billing: Billing) -> None:
    doubted, sound = two_equal(billing)
    billing.doubt(doubted)

    assert billing.dana.call("read", path=doubted)["in_doubt"] == LINE
    assert "in_doubt" not in billing.dana.call("read", path=sound)


def test_the_briefings_pinned_memories_show_the_in_doubt_line_with_the_count_and_reasons(billing: Billing) -> None:
    path = promote_keeping_both(billing.owner, HALF_UP)
    billing.owner.call("pin", path=path)
    billing.doubt(path)

    briefing = added_context(billing.dana.as_session("briefed").start())

    assert f"({path})" in briefing
    assert LINE in briefing


def test_a_pinned_topics_memories_show_the_in_doubt_line(billing: Billing) -> None:
    path = promote_keeping_both(billing.owner, {**HALF_UP, "topic": "Rounding"})
    billing.owner.call("pin", path=path.rsplit("/", 1)[0])
    billing.doubt(path)

    briefing = added_context(billing.dana.as_session("briefed-topic").start())

    assert HALF_UP["title"] in briefing
    assert LINE in briefing


def test_the_similar_memory_answer_on_save_marks_a_similar_memory_that_is_in_doubt(billing: Billing) -> None:
    doubted, sound = two_equal(billing)
    billing.doubt(doubted)

    saved: dict[str, Any] = billing.dana.call("remember", **BANKERS)

    similar = {each["path"]: each for each in saved["similar"]}
    assert similar[doubted]["in_doubt"] == LINE
    assert "in_doubt" not in similar[sound]


def test_once_its_doubt_is_rejected_a_memory_ranks_as_before_and_loses_the_mark(billing: Billing) -> None:
    paths = two_equal(billing)
    before_recall, before_search = recalled(billing.dana, paths, "before"), searched(billing.dana, paths)
    challenge_id = billing.doubt_once(before_search[0])
    assert searched(billing.dana, paths) == before_search[::-1]

    billing.owner.call("decide_challenge", challenge_id=challenge_id, decision="reject")

    assert recalled(billing.dana, paths, "after") == before_recall
    assert searched(billing.dana, paths) == before_search
    assert "In doubt" not in added_context(billing.dana.as_session("unmarked").prompt(QUERY))
    assert all("in_doubt" not in billing.dana.call("read", path=path) for path in paths)


def test_in_doubt_penalty_reads_its_environment_variable_and_defaults_to_one_half() -> None:
    assert Settings.from_env({}).in_doubt_penalty == 0.5
    assert Settings.from_env({"SHARED_MEMORY_IN_DOUBT_PENALTY": "0.25"}).in_doubt_penalty == 0.25
