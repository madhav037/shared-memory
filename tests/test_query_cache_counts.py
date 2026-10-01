"""How often the query cache saves a model run, counted by where the query came from and written to the log (#166).

One server takes every query here: recall and the search tool reach it as a session does, console search through the
console's JSON API. The clock only ever moves forward, so a test's period is its own.
"""

from __future__ import annotations

import itertools
import logging
import os
import re
import uuid

import pytest

from shared_memory.app import show_log
from shared_memory.config import Settings
from tests.support import Console, ConsoleClient, Session, ask, signed_in_owner

_ACCOUNTS = itertools.count(16601)
_COUNTS = re.compile(r"(recall|console-search|search) hits=(\d+) misses=(\d+)")

Counts = dict[str, tuple[int, int]]


def counts(part: str) -> Counts:
    """One part of the line, as each source's (hits, misses)."""
    return {source: (int(hits), int(misses)) for source, hits, misses in _COUNTS.findall(part)}


def lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.getMessage().startswith("Query cache")]


def unique(words: str) -> str:
    """A query no other test has asked, so the first time it is asked is a miss."""
    return f"{words} {uuid.uuid4().hex}"


@pytest.fixture
def working(console: Console) -> tuple[ConsoleClient, Session]:
    """A member signed in to the console with a session in a project, at the start of a period with nothing counted."""
    client = console.client()
    account = next(_ACCOUNTS)
    owner = signed_in_owner(console, client, f"cache-{account}", account)
    project = owner.call("create_project", name="Billing")["project_id"]
    session = owner.in_project(project, "billing-api")
    console.clock.advance(minutes=console.server.settings.query_cache_log_minutes)
    session.call("search", query=unique("close the period before"))
    return client, session


def test_repeats_are_hits_and_new_queries_misses_each_under_where_it_came_from(
    console: Console, working: tuple[ConsoleClient, Session], caplog: pytest.LogCaptureFixture
) -> None:
    client, session = working
    prompt, searched, in_console, other = (unique(words) for words in ("refunds", "rounding", "retries", "queues"))

    session.prompt(prompt)
    session.prompt(prompt)
    for _ in range(3):
        session.call("search", query=searched)
    ask(client, "/api/search", query=in_console)
    ask(client, "/api/search", query=other)
    console.clock.advance(minutes=15)
    with caplog.at_level(logging.INFO, logger="shared_memory"):
        ask(client, "/api/search", query=in_console)

    [line] = lines(caplog)
    head, period, _ = line.split(" | ")
    assert head == f"Query cache worker={os.getpid()} minutes=15"
    assert period.startswith("period: ")
    assert counts(period) == {"recall": (1, 1), "search": (2, 1), "console-search": (1, 2)}


def test_a_query_asked_from_somewhere_else_is_a_hit_for_where_it_was_asked_again(
    console: Console, working: tuple[ConsoleClient, Session], caplog: pytest.LogCaptureFixture
) -> None:
    client, session = working
    query = unique("how do refunds round")

    session.prompt(query)
    session.call("search", query=query)
    console.clock.advance(minutes=15)
    with caplog.at_level(logging.INFO, logger="shared_memory"):
        ask(client, "/api/search", query=query)

    [line] = lines(caplog)
    assert counts(line.split(" | ")[1]) == {"recall": (0, 1), "search": (1, 0), "console-search": (1, 0)}


def test_the_line_is_written_once_a_period_and_carries_the_totals_since_start(
    console: Console, working: tuple[ConsoleClient, Session], caplog: pytest.LogCaptureFixture
) -> None:
    _, session = working
    query = unique("where are invoices kept")

    with caplog.at_level(logging.INFO, logger="shared_memory"):
        session.call("search", query=query)
        console.clock.advance(minutes=14)
        session.call("search", query=query)
        assert lines(caplog) == []

        console.clock.advance(minutes=1)
        session.call("search", query=query)
        console.clock.advance(minutes=40)
        session.call("search", query=query)

    first, second = lines(caplog)
    assert "minutes=15 " in first and "minutes=40 " in second
    assert counts(first.split(" | ")[1])["search"] == (2, 1)
    assert counts(second.split(" | ")[1]) == {"recall": (0, 0), "search": (1, 0), "console-search": (0, 0)}
    before, after = (counts(line.split(" | ")[2]) for line in (first, second))
    assert second.split(" | ")[2].startswith("since start: ")
    assert after["search"] == (before["search"][0] + 1, before["search"][1])
    assert before["search"][1] >= 2  # this test's miss and the one that closed the period before it


def test_the_period_is_a_setting_read_from_the_environment() -> None:
    assert Settings.from_env({}).query_cache_log_minutes == 15
    assert Settings.from_env({"SHARED_MEMORY_QUERY_CACHE_LOG_MINUTES": "2.5"}).query_cache_log_minutes == 2.5


def test_a_served_worker_shows_the_line(capsys: pytest.CaptureFixture[str]) -> None:
    """Nothing else sets the server's own logger up, and Python drops what is below a warning until something does."""
    log = logging.getLogger("shared_memory")
    before = (log.level, list(log.handlers))
    try:
        show_log()
        show_log()
        log.info("Query cache worker=1 minutes=15")
    finally:
        log.setLevel(before[0])
        log.handlers[:] = before[1]

    assert capsys.readouterr().err.count("Query cache worker=1 minutes=15") == 1
