"""A member reaches only their team's own memory folder: never through a link placed in it, however the path is built."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared_memory.memory import Memory
from tests.support import Session, Team, ToolRefused


@pytest.fixture
def member(team: Team) -> Session:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    return team.owner().in_project(project, "billing-api")


def linked_folder(team: Team, tmp_path: Path) -> str:
    """A folder of someone else's memory, linked into this team's team memory; the memory path through the link."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "secret.md").write_text(Memory("Secret", "Not yours.", "convention", "x", "b").to_text(), "utf-8")
    conventions = team.server.settings.memory_root / team.code / "team" / "conventions"
    conventions.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(elsewhere, conventions / "linked", target_is_directory=True)
    except OSError:
        pytest.skip("this machine can't make links")
    return "team/conventions/linked/secret.md"


def test_a_memory_reached_through_a_linked_folder_is_refused(team: Team, member: Session, tmp_path: Path) -> None:
    path = linked_folder(team, tmp_path)

    with pytest.raises(ToolRefused, match="outside your team's memory"):
        member.call("read", path=path)


def test_tree_leaves_a_linked_folder_out(team: Team, member: Session, tmp_path: Path) -> None:
    member.call("remember", title="Kept", summary="Yours.", type="convention", body="b")
    linked_folder(team, tmp_path)

    paths = [m["path"] for f in member.call("tree")["folders"] for m in f["memories"]]

    assert not [path for path in paths if "linked" in path]


def test_a_path_that_climbs_out_is_refused(member: Session) -> None:
    with pytest.raises(ToolRefused):
        member.call("read", path="team/conventions/../../../elsewhere/secret.md")
