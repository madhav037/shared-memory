"""The memory folder: memory files on disk, the source of truth, with every change committed to git (ADR-0002, ADR-0003).

This writes and reads the files as they stand now. What they said before is `history.py`, which answers by parsing
git's output rather than by touching the filesystem.

Saves take turns: one change to the memory folder is applied and committed at a time, and whatever a save reads to
decide what it writes, it reads through its `Change`, inside that same turn. A file is written beside its place and
renamed into it, so a reader sees the old file or the new one, never part of one. Reads outside a save don't wait
for their turn: a listing skips a memory deleted while it was being listed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol, TypeVar

from shared_memory.errors import Refused
from shared_memory.memory import INDEX_NAME, Memory, slugify

T = TypeVar("T")


@dataclass(frozen=True)
class Committer:
    member_id: str
    name: str
    # The coding agent the change came from, kept with the version as a Coding-Agent trailer.
    agent: str | None = None


@dataclass
class Change:
    """A set of file changes in one team's folder that lands as a single commit.

    It exists only inside its save's turn, so nothing it reads can change before its writes land. Its commit message
    can be set once it has read the memory the message names.
    """

    store: MemoryStore
    team: str
    message: str
    writes: dict[PurePosixPath, Memory] = field(default_factory=dict)
    deletes: set[PurePosixPath] = field(default_factory=set)

    def read(self, path: PurePosixPath) -> Memory:
        """A memory as this change leaves it, refusing one that isn't there."""
        if path in self.writes:
            return self.writes[path]
        if path in self.deletes:
            raise Refused(f"There is no memory at {str(path)!r}.")
        return self.store.read(self.team, path)

    def exists(self, path: PurePosixPath) -> bool:
        return path in self.writes or (path not in self.deletes and self.store.exists(self.team, path))

    def write(self, path: PurePosixPath, memory: Memory) -> None:
        self.deletes.discard(path)
        self.writes[path] = memory

    def delete(self, path: PurePosixPath) -> None:
        self.writes.pop(path, None)
        self.deletes.add(path)

    def new_path(self, folder: PurePosixPath, title: str) -> PurePosixPath:
        base = slugify(title)
        if base == "index":
            base = "index-memory"
        candidate = folder / f"{base}.md"
        number = 2
        while self.exists(candidate):
            candidate = folder / f"{base}-{number}.md"
            number += 1
        return candidate


class ChangeListener(Protocol):
    def on_change(self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]) -> None: ...


def confine(root: Path, team: str, path: PurePosixPath) -> Path:
    """Where a memory path lands on disk, refusing anything that would leave the team's own folder."""
    team_dir = (root / team).resolve()
    target = (team_dir / Path(*path.parts)).resolve() if path.parts else team_dir
    if target != team_dir and team_dir not in target.parents:
        raise Refused(f"{str(path)!r} is outside your team's memory.")
    return target


def _settled(action: Callable[[], T]) -> T:
    """Run a file operation, waiting out another thread that has the file open or half-renamed.

    Only Windows refuses these while a file is open elsewhere; everywhere else the first attempt stands.
    """
    for attempt in range(100):
        try:
            return action()
        except PermissionError:
            if sys.platform != "win32" or attempt == 99:
                raise
            time.sleep(0.01)
    raise AssertionError("unreachable")


def write_whole(file: Path, text: str) -> None:
    """Write a file beside its place and rename it in, so no reader ever sees it half-written."""
    file.parent.mkdir(parents=True, exist_ok=True)
    # A leading dot and no .md suffix keep a file still being written out of every listing.
    pending = file.with_name(f".{file.name}.{uuid.uuid4().hex}.saving")
    try:
        pending.write_text(text, encoding="utf-8", newline="\n")
        _settled(lambda: os.replace(pending, file))
    finally:
        pending.unlink(missing_ok=True)


def read_whole(file: Path) -> str:
    """A file's text, or FileNotFoundError when there is no file there, even for a moment mid-rename."""
    if file.is_dir():
        raise FileNotFoundError(file)
    return _settled(lambda: file.read_text(encoding="utf-8"))


class MemoryStore:
    def __init__(self, root: Path, listeners: Iterable[ChangeListener] = ()) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._turn = threading.Lock()
        self._listeners = list(listeners)
        if not (self._root / ".git").exists():
            self._git("init", "-q", "-b", "main")
            self._git("config", "core.autocrlf", "false")
            self._git("config", "core.quotepath", "false")

    def _git(self, *args: str, committer: Committer | None = None) -> str:
        env = dict(os.environ)
        env.update(
            GIT_COMMITTER_NAME="Shared Memory",
            GIT_COMMITTER_EMAIL="server@shared-memory.invalid",
            GIT_AUTHOR_NAME=committer.name if committer else "Shared Memory",
            GIT_AUTHOR_EMAIL=f"{committer.member_id}@members.shared-memory.invalid"
            if committer
            else "server@shared-memory.invalid",
        )
        result = subprocess.run(
            ["git", "-C", str(self._root), *args], env=env, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def _file(self, team: str, path: PurePosixPath) -> Path:
        return confine(self._root, team, path)

    def exists(self, team: str, path: PurePosixPath) -> bool:
        return self._file(team, path).is_file()

    def list_folder(
        self, team: str, folder: PurePosixPath
    ) -> tuple[list[tuple[PurePosixPath, Memory]], list[PurePosixPath]]:
        """The memories directly in a folder (sorted by title) and its subfolders."""
        try:
            entries = list(self._file(team, folder).iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return [], []
        memories: list[tuple[PurePosixPath, Memory]] = []
        folders: list[PurePosixPath] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                folders.append(folder / entry.name)
            elif entry.suffix == ".md" and entry.name != INDEX_NAME:
                try:
                    memories.append((folder / entry.name, Memory.from_text(read_whole(entry))))
                except (Refused, FileNotFoundError):
                    continue  # not a memory, or deleted since the folder was listed
        memories.sort(key=lambda item: (item[1].title.lower(), str(item[0])))
        return memories, sorted(folders)

    def walk(self, team: str, root: PurePosixPath) -> Iterator[tuple[PurePosixPath, list[tuple[PurePosixPath, Memory]]]]:
        """Every folder under root, depth first in path order, with the memories directly in it."""
        memories, folders = self.list_folder(team, root)
        yield root, memories
        for folder in folders:
            yield from self.walk(team, folder)

    def _write_index(self, team: str, folder: PurePosixPath) -> None:
        directory = self._file(team, folder)
        index = directory / INDEX_NAME
        memories, folders = self.list_folder(team, folder)
        if not memories and not folders:
            _settled(lambda: index.unlink(missing_ok=True))
            if folder.parts and directory.is_dir() and not any(directory.iterdir()):
                _settled(directory.rmdir)
            return
        lines = [f"# {folder if folder.parts else 'Memory'}", ""]
        if memories:
            lines += ["## Memories", ""]
            lines += [f"- [{memory.title}]({path.name}): {memory.summary}" for path, memory in memories]
            lines.append("")
        if folders:
            lines += ["## Folders", ""]
            lines += [f"- [{sub.name}/]({sub.name}/{INDEX_NAME})" for sub in folders]
            lines.append("")
        write_whole(index, "\n".join(lines))

    def text(self, team: str, path: PurePosixPath) -> str:
        """The memory file exactly as it is on disk: its header and its body, as every Claude reads it."""
        try:
            return read_whole(self._file(team, path))
        except FileNotFoundError:
            raise Refused(f"There is no memory at {str(path)!r}.") from None

    def extent(self, team: str, folder: PurePosixPath) -> tuple[int, datetime | None]:
        """How many memories a folder holds at any depth, and when the newest of them last changed."""
        directory = self._file(team, folder)
        if not directory.is_dir():
            return 0, None
        changed: list[float] = []
        # os.walk passes over a folder removed while it walks; a file removed after its folder was listed is skipped.
        for below, _, names in os.walk(directory):
            for name in names:
                if name.startswith(".") or not name.endswith(".md") or name == INDEX_NAME:
                    continue
                try:
                    changed.append(os.stat(os.path.join(below, name)).st_mtime)
                except FileNotFoundError:
                    continue
        if not changed:
            return 0, None
        return len(changed), datetime.fromtimestamp(max(changed)).astimezone()

    def changed(self, team: str, path: PurePosixPath) -> datetime | None:
        """When one memory file last changed on disk."""
        try:
            return datetime.fromtimestamp(self._file(team, path).stat().st_mtime).astimezone()
        except FileNotFoundError:
            return None

    def read(self, team: str, path: PurePosixPath) -> Memory:
        return Memory.from_text(self.text(team, path))

    @contextmanager
    def _one_save_at_a_time(self) -> Iterator[None]:
        """The one place saves are serialized. Only this process saves, so a mutex between its threads is enough."""
        with self._turn:
            yield

    @contextmanager
    def change(self, team: str, committer: Committer, message: str = "") -> Iterator[Change]:
        """One save, in its turn: read what it changes and write through the Change, and it lands as one commit.

        A refusal inside the block leaves the memory folder as it was.
        """
        with self._one_save_at_a_time():
            change = Change(self, team, message)
            yield change
            self._apply(change, committer)

    def _apply(self, change: Change, committer: Committer) -> None:
        team = change.team
        folders: set[PurePosixPath] = set()
        for path, memory in change.writes.items():
            file = self._file(team, path)
            if file.name == INDEX_NAME:
                raise Refused(f"{INDEX_NAME} is reserved for folder indexes.")
            write_whole(file, memory.to_text())
            folders.update(path.parents)
        for path in change.deletes:
            file = self._file(team, path)
            _settled(lambda: file.unlink(missing_ok=True))
            folders.update(path.parents)
        if not folders:
            return
        for folder in sorted(folders, key=lambda f: len(f.parts), reverse=True):
            self._write_index(team, folder)
        self._git("add", "-A", "--", str(self._file(team, PurePosixPath())))
        if self._git_has_staged_changes():
            trailer = f"\n\nCoding-Agent: {committer.agent}" if committer.agent else ""
            self._git("commit", "-q", "-m", change.message + trailer, committer=committer)
        for listener in self._listeners:
            listener.on_change(team, dict(change.writes), set(change.deletes))

    def subscribe(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def teams(self) -> list[str]:
        return sorted(d.name for d in self._root.iterdir() if d.is_dir() and not d.name.startswith("."))

    def _git_has_staged_changes(self) -> bool:
        result = subprocess.run(["git", "-C", str(self._root), "diff", "--cached", "--quiet"], check=False)
        return result.returncode == 1
