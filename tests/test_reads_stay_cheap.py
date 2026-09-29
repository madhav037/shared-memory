"""The work a read does stays small as memory grows: under load, the server runs one thread of Python at a time, so
per-call work that grows with the team's memory, or that repeats for every call, caps how many calls it can answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from shared_memory import app as app_module
from shared_memory import store as store_module
from tests.support import Session, Team


@pytest.fixture
def member(team: Team) -> Session:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    return team.owner().in_project(project, "billing-api")


class Count:
    def __init__(self) -> None:
        self.count = 0

    def take(self) -> int:
        count, self.count = self.count, 0
        return count


@pytest.fixture
def confinements(monkeypatch: pytest.MonkeyPatch) -> Iterator[Count]:
    counted = Count()
    confine = store_module.confine

    def counting(root: Path, team: str, path: object) -> Path:
        counted.count += 1
        return confine(root, team, path)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module, "confine", counting)
    yield counted


@pytest.fixture
def listings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Count]:
    """How many times the server lists its tools for itself, before running a call. (A client that connects afresh
    lists them too, to learn their output schemas; that listing is the client's own.)"""
    counted = Count()
    listed = app_module._listed_tool_schema

    async def counting(*args: Any) -> Any:
        counted.count += 1
        return await listed(*args)

    monkeypatch.setattr(app_module, "_listed_tool_schema", counting)
    yield counted


def test_tree_checks_each_root_once_however_many_folders_it_walks(member: Session, confinements: Count) -> None:
    for kind in ("convention", "decision", "architecture", "gotcha"):
        for n in range(3):
            member.call("remember", title=f"{kind} {n}", summary="S.", type=kind, body="b", topic=f"topic {n}")
    confinements.take()

    folders = member.call("tree")["folders"]

    assert len(folders) >= 12
    assert confinements.take() <= 2


def test_calling_a_tool_does_not_list_every_tool_each_time(member: Session, listings: Count) -> None:
    member.call("search", query="anything")
    listings.take()

    for n in range(5):
        member.call("search", query=f"money {n}")

    assert listings.take() == 0
