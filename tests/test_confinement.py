"""A member reaches only their company's own memory folder: never through a link placed in it, however the path is built."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared_memory.memory import Memory
from tests.support import Session, Company, ToolRefused


@pytest.fixture
def member(company: Company) -> Session:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    return company.owner().in_project(project, "billing-api")


def linked_folder(company: Company, tmp_path: Path) -> str:
    """A folder of someone else's memory, linked into this company's memory; the memory path through the link."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "secret.md").write_text(Memory("Secret", "Not yours.", "convention", "x", "b").to_text(), "utf-8")
    conventions = company.server.settings.memory_root / company.code / "company" / "conventions"
    conventions.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(elsewhere, conventions / "linked", target_is_directory=True)
    except OSError:
        pytest.skip("this machine can't make links")
    return "company/conventions/linked/secret.md"


def test_a_memory_reached_through_a_linked_folder_is_refused(company: Company, member: Session, tmp_path: Path) -> None:
    path = linked_folder(company, tmp_path)

    with pytest.raises(ToolRefused, match="outside your company's memory"):
        member.call("read", path=path)


def test_the_old_team_path_through_a_linked_folder_is_refused_too(
    company: Company, member: Session, tmp_path: Path
) -> None:
    path = linked_folder(company, tmp_path).replace("company/", "company/", 1)

    with pytest.raises(ToolRefused, match="outside your company's memory"):
        member.call("read", path=path)


def test_tree_leaves_a_linked_folder_out(company: Company, member: Session, tmp_path: Path) -> None:
    member.call("remember", title="Kept", summary="Yours.", type="convention", body="b")
    linked_folder(company, tmp_path)

    paths = [m["path"] for f in member.call("tree")["folders"] for m in f["memories"]]

    assert not [path for path in paths if "linked" in path]


def test_a_path_that_climbs_out_is_refused(member: Session) -> None:
    with pytest.raises(ToolRefused):
        member.call("read", path="company/conventions/../../../elsewhere/secret.md")
