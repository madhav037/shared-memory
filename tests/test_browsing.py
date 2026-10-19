from __future__ import annotations

import subprocess

import pytest

from tests.support import Session, Team


@pytest.fixture
def member(team: Team) -> Session:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    return team.owner().in_project(project, "billing-api")


def git(team: Team, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), *args], capture_output=True, text=True, check=True
    ).stdout


def folder_of(path: str) -> str:
    return path.rsplit("/", 1)[0]


def test_saving_a_memory_updates_its_folder_index_in_the_same_commit(team: Team, member: Session) -> None:
    saved = member.call("remember", title="Retries", summary="Billing retries twice.", type="convention", body="b")
    index = f"{team.code}/{folder_of(saved['path'])}/index.md"

    changed = git(team, "show", "--name-only", "--format=", "HEAD").split()

    assert index in changed
    assert "- [Retries](retries.md): Billing retries twice." in git(team, "show", f"HEAD:{index}")


def test_editing_and_deleting_keep_the_folder_index_current(team: Team, member: Session) -> None:
    kept = member.call("remember", title="Kept", summary="Stays.", type="gotcha", body="b")
    gone = member.call("remember", title="Gone", summary="Goes.", type="gotcha", body="b")
    member.call("edit_memory", path=kept["path"], summary="Stays, reworded.")
    member.call("delete_memory", path=gone["path"])

    index = git(team, "show", f"HEAD:{team.code}/{folder_of(kept['path'])}/index.md")

    assert "- [Kept](kept.md): Stays, reworded." in index
    assert "Gone" not in index


def test_list_returns_a_folders_memories_with_their_summaries(member: Session) -> None:
    first = member.call("remember", title="Retries", summary="Billing retries twice.", type="convention", body="b")
    member.call("remember", title="Currency", summary="Amounts are in cents.", type="convention", body="b")

    listing = member.call("list", folder=folder_of(first["path"]))

    assert [(m["title"], m["summary"]) for m in listing["memories"]] == [
        ("Currency", "Amounts are in cents."),
        ("Retries", "Billing retries twice."),
    ]


def test_a_long_subject_is_saved_as_a_topic_of_separate_memories(member: Session) -> None:
    retries = member.call(
        "remember", title="Retries", summary="How retries work.", type="architecture", body="b", topic="API errors"
    )
    member.call(
        "remember", title="Status codes", summary="Which codes we return.", type="architecture", body="b", topic="API errors"
    )

    topic = folder_of(retries["path"])
    listing = member.call("list", folder=topic)

    assert topic.endswith("/architecture/api-errors")
    assert [m["title"] for m in listing["memories"]] == ["Retries", "Status codes"]
    assert member.call("read", path=retries["path"])["title"] == "Retries"


def test_a_types_folder_lists_its_topics(member: Session) -> None:
    saved = member.call("remember", title="Retries", summary="s", type="architecture", body="b", topic="API errors")

    listing = member.call("list", folder=folder_of(folder_of(saved["path"])))

    assert listing["folders"] == [folder_of(saved["path"])]


def test_tree_shows_the_whole_project_with_summaries(team: Team, member: Session) -> None:
    saved = member.call("remember", title="Retries", summary="Billing retries twice.", type="convention", body="b")

    tree = member.call("tree")

    folders = {entry["folder"]: entry["memories"] for entry in tree["folders"]}
    assert folders[folder_of(saved["path"])] == [
        {"path": saved["path"], "title": "Retries", "summary": "Billing retries twice.", "foundation": None, "pending": []}
    ]


def test_tree_can_show_one_level(member: Session) -> None:
    member.call("remember", title="Retries", summary="s", type="convention", body="b")

    assert member.call("tree", level="project")["folders"] == []
    assert len(member.call("tree", level="personal")["folders"]) == 1


def test_list_refuses_folders_outside_the_team(member: Session) -> None:
    assert "outside" in member.refusal("list", folder="../somewhere-else")


def commit_files(team: Team) -> list[str]:
    return git(team, "show", "--name-only", "--format=", "HEAD").split()


def index_at_head(team: Team, folder: str) -> str:
    return git(team, "show", f"HEAD:{team.code}/{folder}/index.md")


def test_a_save_into_an_existing_folder_leaves_every_parent_index_out_of_its_commit(team: Team, member: Session) -> None:
    first = member.call("remember", title="Retries", summary="Billing retries twice.", type="convention", body="b")
    second = member.call("remember", title="Currency", summary="Amounts are in cents.", type="convention", body="b")

    changed = commit_files(team)

    assert folder_of(first["path"]) == folder_of(second["path"])
    assert [name for name in changed if name.endswith("/index.md")] == [f"{team.code}/{folder_of(second['path'])}/index.md"]


def test_the_first_memory_in_a_new_folder_appears_in_its_parents_listing(team: Team, member: Session) -> None:
    member.call("remember", title="Retries", summary="Billing retries twice.", type="convention", body="b")
    gotcha = member.call("remember", title="Locks", summary="Take the lock.", type="gotcha", body="b")
    folder = folder_of(gotcha["path"])
    parent, name = folder.rsplit("/", 1)

    assert f"- [{name}/]({name}/index.md)" in index_at_head(team, parent)
    assert f"{team.code}/{parent}/index.md" in commit_files(team)


def test_deleting_the_last_memory_in_a_folder_removes_it_from_its_parents_listing(team: Team, member: Session) -> None:
    member.call("remember", title="Retries", summary="Billing retries twice.", type="convention", body="b")
    gotcha = member.call("remember", title="Locks", summary="Take the lock.", type="gotcha", body="b")
    folder = folder_of(gotcha["path"])
    parent, name = folder.rsplit("/", 1)

    member.call("delete_memory", path=gotcha["path"])

    assert f"{name}/" not in index_at_head(team, parent)
    assert f"{team.code}/{folder}/index.md" in commit_files(team)


def test_promoting_moves_the_memory_between_listings(team: Team, member: Session) -> None:
    personal = member.call("remember", title="Retries", summary="Billing retries twice.", type="convention", body="b")
    old_folder = folder_of(personal["path"])

    result = member.call("promote", path=personal["path"], level="project")
    assert result["status"] == "promoted", result
    new_folder = folder_of(result["path"])

    assert new_folder != old_folder
    assert "- [Retries](retries.md)" in index_at_head(team, new_folder)
    assert git(team, "ls-tree", "-r", "--name-only", "HEAD", f"{team.code}/{old_folder}/").strip() == ""
