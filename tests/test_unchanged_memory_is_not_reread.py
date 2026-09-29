"""Reading memory reads again only what changed: an unchanged memory file is parsed once, not on every read (#136).

Whatever a read returns stays what the files say, right after a save, an edit, a delete, a promote and a retire, and
after a file is changed on disk outside the server.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest

from shared_memory.memory import Memory
from shared_memory.store import MemoryStore
from tests.support import NPM, Session, Team, promote_now


@pytest.fixture
def member(team: Team) -> Session:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    return team.owner().in_project(project, "billing-api")


class Parses:
    """How many memory files the server has parsed since the count was last taken."""

    def __init__(self) -> None:
        self.count = 0

    def take(self) -> int:
        count, self.count = self.count, 0
        return count


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> Iterator[Parses]:
    counted = Parses()
    parse = Memory.from_text.__func__  # type: ignore[attr-defined]

    def counting(cls: type[Memory], text: str) -> Memory:
        counted.count += 1
        result: Memory = parse(cls, text)
        return result

    monkeypatch.setattr(Memory, "from_text", classmethod(counting))
    yield counted


def remember(session: Session, title: str, summary: str = "What it says.") -> str:
    path: str = session.call("remember", title=title, summary=summary, type="convention", body=f"All about {title}.")["path"]
    return path


def summaries(session: Session, level: str | None = None) -> dict[str, str]:
    return {m["path"]: m["summary"] for f in session.call("tree", level=level)["folders"] for m in f["memories"]}


def folder_of(path: str) -> str:
    return path.rsplit("/", 1)[0]


def test_tree_parses_only_the_memories_that_changed_since_it_last_ran(member: Session, parses: Parses) -> None:
    paths = [remember(member, f"Convention {n}") for n in range(6)]
    member.call("tree")
    parses.take()

    member.call("tree")
    unchanged = parses.take()
    member.call("edit_memory", path=paths[0], summary="Reworded.")
    parses.take()
    tree = summaries(member)
    after_an_edit = parses.take()

    assert unchanged == 0
    assert after_an_edit <= 1
    assert tree[paths[0]] == "Reworded."


def test_a_saved_edited_and_deleted_memory_reads_fresh_everywhere(member: Session) -> None:
    kept = remember(member, "Kept", "As first saved.")
    gone = remember(member, "Gone")
    member.call("tree")
    member.call("list", folder=folder_of(kept))
    member.call("read", path=kept)

    added = remember(member, "Added", "Saved after the first reads.")
    member.call("edit_memory", path=kept, summary="Edited after the first reads.")
    member.call("delete_memory", path=gone)

    tree = summaries(member)
    listed = {m["path"]: m["summary"] for m in member.call("list", folder=folder_of(kept))["memories"]}
    expected = {kept: "Edited after the first reads.", added: "Saved after the first reads."}
    assert tree == expected
    assert listed == expected
    assert member.call("read", path=kept)["summary"] == "Edited after the first reads."
    assert "no memory" in member.refusal("read", path=gone)


def test_a_promoted_memory_reads_fresh_at_both_levels(member: Session) -> None:
    personal = member.call("remember", **NPM)["path"]
    assert personal in summaries(member, "personal")
    member.call("tree", level="project")

    promoted = member.call("promote", path=personal, level="project")

    assert promoted["status"] == "promoted", promoted
    assert personal not in summaries(member, "personal")
    assert promoted["path"] in summaries(member, "project")
    assert "no memory" in member.refusal("read", path=personal)


def test_a_retired_memory_reads_as_retired_straight_away(member: Session) -> None:
    path = promote_now(member, NPM)
    assert member.call("read", path=path)["status"] == "active"
    member.call("list", folder=folder_of(path))

    member.call("retire", path=path)

    assert member.call("read", path=path)["status"] == "retired"
    listed = {m["path"]: m["status"] for m in member.call("list", folder=folder_of(path))["memories"]}
    assert listed[path] == "retired"


def test_an_edit_that_fails_and_is_undone_reads_as_it_was(team: Team, member: Session) -> None:
    path = remember(member, "Edited and undone", "As first saved.")
    assert member.call("read", path=path)["summary"] == "As first saved."
    # main held by a process that died holding it, so the edit fails once its file is written.
    lock = team.server.settings.memory_root / ".git" / "refs" / "heads" / "main.lock"
    lock.write_text("")
    try:
        refusal = member.refusal("edit_memory", path=path, summary="Never landed.")
    finally:
        lock.unlink()

    assert "not saved" in refusal
    assert member.call("read", path=path)["summary"] == "As first saved."
    assert summaries(member)[path] == "As first saved."


def test_a_file_changed_on_disk_outside_the_server_is_noticed(team: Team, member: Session) -> None:
    path = remember(member, "Edited by hand", "As the server saved it.")
    assert summaries(member)[path] == "As the server saved it."
    file = Path(team.server.settings.memory_root, team.code, *PurePosixPath(path).parts)

    # Edited in place, the way a text editor saves, rather than written beside it and renamed in.
    with file.open("r+", encoding="utf-8", newline="\n") as edited:
        text = edited.read().replace("As the server saved it.", "As a member rewrote it by hand.")
        edited.seek(0)
        edited.write(text)
        edited.truncate()

    assert summaries(member)[path] == "As a member rewrote it by hand."
    assert member.call("read", path=path)["summary"] == "As a member rewrote it by hand."


def test_a_memory_read_back_can_be_changed_without_changing_what_the_next_read_returns(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    path = PurePosixPath("team", "conventions", "kept.md")
    (tmp_path / "t" / "team" / "conventions").mkdir(parents=True)
    (tmp_path / "t" / path).write_text(Memory("Kept", "S.", "convention", "a", "b").to_text(), encoding="utf-8")

    first = store.read("t", path)
    first.title = "Changed by a caller"
    first.related_files.append("src/changed.py")

    again = store.read("t", path)
    assert (again.title, again.related_files) == ("Kept", [])


def test_a_save_ending_mid_read_only_stops_its_own_files_being_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parses: Parses
) -> None:
    """Saves in other areas end many times a second; one ending while a file is parsed must not throw that parse away
    unless the save changed that file."""
    store = MemoryStore(tmp_path)
    folder = tmp_path / "t" / "team" / "conventions"
    folder.mkdir(parents=True)
    paths = {}
    for name in ("read", "saved"):
        (folder / f"{name}.md").write_text(Memory(name, "S.", "convention", "a", "b").to_text(), encoding="utf-8")
        paths[name] = PurePosixPath("team", "conventions", f"{name}.md")
    counting = Memory.from_text.__func__  # type: ignore[attr-defined]

    def a_save_ends_meanwhile(changed: str) -> None:
        def parse(cls: type[Memory], text: str) -> Memory:
            store._parsed.forget([folder / f"{changed}.md"])
            result: Memory = counting(cls, text)
            return result

        monkeypatch.setattr(Memory, "from_text", classmethod(parse))

    a_save_ends_meanwhile("saved")
    store.read("t", paths["read"])
    monkeypatch.setattr(Memory, "from_text", classmethod(counting))
    parses.take()
    store.read("t", paths["read"])
    kept_despite_another_save = parses.take()

    a_save_ends_meanwhile("read")
    store.read("t", paths["saved"])
    store.read("t", paths["read"])
    monkeypatch.setattr(Memory, "from_text", classmethod(counting))
    parses.take()
    store.read("t", paths["read"])
    dropped_after_its_own_save = parses.take()

    assert kept_despite_another_save == 0
    assert dropped_after_its_own_save == 1


def test_parsed_memories_are_kept_within_a_bound(tmp_path: Path, parses: Parses) -> None:
    body = "x" * 4000
    store = MemoryStore(tmp_path, parsed_characters=10_000)
    folder = tmp_path / "t" / "team" / "conventions"
    folder.mkdir(parents=True)
    paths = []
    for n in range(4):
        (folder / f"m{n}.md").write_text(Memory(f"M{n}", "S.", "convention", "a", body).to_text(), encoding="utf-8")
        paths.append(PurePosixPath("team", "conventions", f"m{n}.md"))

    for path in paths:
        store.read("t", path)
    parses.take()
    store.read("t", paths[-1])
    kept = parses.take()
    store.read("t", paths[0])
    evicted = parses.take()

    assert kept == 0
    assert evicted == 1
