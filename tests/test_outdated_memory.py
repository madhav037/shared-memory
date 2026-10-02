"""Outdated memory: a memory no coding agent has used for `outdated_after_days` is labelled possibly outdated."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import (
    Console,
    ConsoleClient,
    RunningServer,
    Session,
    Team,
    TestClock,
    ask,
    fresh_database,
    new_team,
    promote_keeping_both,
    signed_in_owner,
)

PNPM = {
    "title": "Use pnpm, not npm",
    "summary": "Every package is managed with pnpm.",
    "type": "convention",
    "body": "We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
}


def labelled(session: Session, path: str) -> bool:
    read = session.call("read", path=path)
    assert ("check" in read) is read["possibly_outdated"], read
    return bool(read["possibly_outdated"])


def test_a_memory_unread_for_longer_than_the_setting_is_labelled_on_read(team: Team, owner: Session) -> None:
    path = promote_keeping_both(owner, PNPM)

    team.server.clock.advance(days=59)
    in_use = owner.call("read", path=path)
    team.server.clock.advance(days=61)
    unused = owner.call("read", path=path)

    assert in_use["possibly_outdated"] is False
    assert "check" not in in_use
    assert unused["possibly_outdated"] is True
    assert "61 days" in unused["check"]
    assert "before relying on it" in unused["check"]
    assert "retire" in unused["check"]


def test_the_read_that_shows_the_label_clears_it(team: Team, owner: Session) -> None:
    path = promote_keeping_both(owner, PNPM)
    team.server.clock.advance(days=61)

    assert labelled(owner, path)
    assert not labelled(owner, path)


def test_recall_is_a_use(team: Team, owner: Session) -> None:
    path = promote_keeping_both(owner, PNPM)
    team.server.clock.advance(days=40)

    owner.prompt("which package manager do we use?")
    team.server.clock.advance(days=40)

    assert not labelled(owner, path)


def test_a_search_hit_is_no_use(team: Team, owner: Session) -> None:
    path = promote_keeping_both(owner, PNPM)
    team.server.clock.advance(days=40)

    found = owner.call("search", query="which package manager do we use?")
    team.server.clock.advance(days=40)

    assert path in [result["path"] for result in found["results"]]
    assert labelled(owner, path)


def test_a_pinned_memory_is_never_labelled_until_it_is_unpinned(team: Team, owner: Session) -> None:
    path = promote_keeping_both(owner, PNPM)
    owner.call("pin", path=path)
    team.server.clock.advance(days=90)

    owner.call("briefing")
    pinned = owner.call("read", path=path)
    team.server.clock.advance(days=90)
    owner.call("unpin", path=path)

    assert pinned["possibly_outdated"] is False
    assert labelled(owner, path)


def test_a_memory_in_a_pinned_topic_is_never_labelled(team: Team, owner: Session) -> None:
    path = promote_keeping_both(owner, {**PNPM, "topic": "packages"})
    owner.call("pin", path=path.rsplit("/", 1)[0])
    team.server.clock.advance(days=90)

    assert not labelled(owner, path)


def test_a_retired_memory_is_never_labelled(team: Team, owner: Session) -> None:
    path = promote_keeping_both(owner, PNPM)
    owner.call("retire", path=path)
    team.server.clock.advance(days=90)

    assert not labelled(owner, path)


def test_saving_a_memory_starts_its_clock_and_editing_it_restarts_it(team: Team, owner: Session) -> None:
    team.server.clock.advance(days=90)
    path = owner.call("remember", **PNPM)["path"]
    team.server.clock.advance(days=40)
    owner.call("edit_memory", path=path, summary="Every package in every repository is managed with pnpm.")
    team.server.clock.advance(days=40)

    assert not labelled(owner, path)


def test_a_promoted_memory_starts_unlabelled(team: Team, owner: Session) -> None:
    personal = owner.call("remember", **PNPM)["path"]
    team.server.clock.advance(days=90)

    promoted = owner.call("promote", path=personal, level="project")

    assert promoted["status"] == "promoted", promoted
    assert not labelled(owner, promoted["path"])


def test_the_number_of_days_is_a_server_setting() -> None:
    assert Settings.from_env({}).outdated_after_days == 60
    assert Settings.from_env({"SHARED_MEMORY_OUTDATED_AFTER_DAYS": "14"}).outdated_after_days == 14


@pytest.fixture
def second_fortnight(server: RunningServer, tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    """A server whose memory is labelled after 14 days instead of 60."""
    settings = dataclasses.replace(
        server.settings,
        database_url=fresh_database("shared_memory_outdated_fortnight"),
        memory_root=tmp_path_factory.mktemp("fortnight-memory"),
        outdated_after_days=14,
    )
    clock = TestClock()
    app = build_app(settings, clock=clock, embedder=FastEmbedEmbedder(settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, clock, portal)
        try:
            yield running
        finally:
            running.stop()


def test_a_shorter_setting_labels_sooner(second_fortnight: RunningServer) -> None:
    team = new_team(second_fortnight)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    owner = team.owner().in_project(project, "billing-api")
    path = promote_keeping_both(owner, PNPM)

    second_fortnight.clock.advance(days=15)

    assert labelled(owner, path)


def test_memory_that_exists_before_last_use_is_kept_counts_as_used_that_day(
    server: RunningServer, tmp_path_factory: pytest.TempPathFactory
) -> None:
    settings = dataclasses.replace(
        server.settings,
        database_url=fresh_database("shared_memory_outdated_existing"),
        memory_root=Path(tmp_path_factory.mktemp("existing-memory")),
    )
    clock = TestClock()
    with start_blocking_portal() as portal:
        before = RunningServer(build_app(settings, clock=clock, embedder=FastEmbedEmbedder(settings.model_cache)), settings, clock, portal)
        team = new_team(before)
        project = team.owner().call("create_project", name="Billing")["project_id"]
        path = promote_keeping_both(team.owner().in_project(project, "billing-api"), PNPM)
        before.stop()
        # The server as it was before it kept last use: no table, and the memory written long ago.
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            conn.execute("DROP TABLE memory_uses")
        clock.advance(days=300)
        shipped = RunningServer(build_app(settings, clock=clock, embedder=FastEmbedEmbedder(settings.model_cache)), settings, clock, portal)
        try:
            owner = dataclasses.replace(team.owner(), server=shipped).in_project(project, "billing-api")
            first_day = owner.call("read", path=path)
            clock.advance(days=61)
            two_months_on = owner.call("read", path=path)
        finally:
            shipped.stop()

    assert first_day["possibly_outdated"] is False
    assert two_months_on["possibly_outdated"] is True


def test_looking_at_a_memory_in_the_console_is_no_use(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-outdated", 2190)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    path = promote_keeping_both(in_project, PNPM)
    console.clock.advance(days=40)
    signed_out.sign_in()  # the console's sign-in lapsed while the clock moved

    ask(signed_out, "/api/memory", path=path)
    console.clock.advance(days=40)

    assert labelled(in_project, path)
