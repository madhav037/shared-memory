"""The memory folder: memory files on disk, the source of truth, with every change committed to git (ADR-0002, ADR-0003).

This writes and reads the files as they stand now. What they said before is `history.py`, which answers by parsing
git's output rather than by touching the filesystem.

Saves take turns: one change to the memory folder is applied and committed at a time, and whatever a save reads to
decide what it writes, it reads through its `Change`, inside that same turn. A file is written beside its place and
renamed into it, so a reader sees the old file or the new one, never part of one. Reads outside a save don't wait
for their turn: a listing skips a memory deleted while it was being listed.

A save lands whole or not at all. Its files are written, then its listeners (the search index, pins) do their part in
transactions left open, then git commits exactly the files the save touched, then whatever else the save asked for
(its audit entry) runs, and only then do the listeners' transactions commit. A failure at any step undoes the steps
before it: the transactions roll back, the commit comes off the branch, and every file the save touched is put back
as it was, so nothing is left on disk for the next save to commit under another member's name.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol, TypeVar

from shared_memory.errors import Refused
from shared_memory.memory import INDEX_NAME, Memory, slugify

T = TypeVar("T")
log = logging.getLogger("shared_memory")


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
    alongside: list[Callable[[], None]] = field(default_factory=list)

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

    def also(self, action: Callable[[], None]) -> None:
        """Something the save does besides its files, such as its audit entry. It runs once the commit is made, and
        if it fails the whole save is undone."""
        self.alongside.append(action)

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
    def on_change(
        self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> AbstractContextManager[None]:
        """Do this listener's part of a save, left uncommitted until the block exits cleanly, undone if it doesn't."""
        ...


class GitFailed(RuntimeError):
    """A git command run on the memory folder failed."""

    def __init__(self, args: tuple[str, ...], stderr: str) -> None:
        super().__init__(f"git {' '.join(args)} failed: {stderr}")
        # git's first line says what went wrong; the lines after it are advice for a person at a terminal.
        self.reason = f"git could not record it ({stderr.splitlines()[0] if stderr else 'it gave no reason'})"


def _reason(error: Exception) -> str:
    """Why a save failed, in one line."""
    if isinstance(error, GitFailed):
        return error.reason
    lines = str(error).strip().splitlines()
    return lines[0] if lines else type(error).__name__


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
            # A memory's path is only ever a path, never a pattern.
            GIT_LITERAL_PATHSPECS="1",
        )
        result = subprocess.run(
            ["git", "-C", str(self._root), *args], env=env, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise GitFailed(args, result.stderr.strip())
        return result.stdout

    def _head(self) -> str | None:
        """The last commit, or None before the first."""
        result = subprocess.run(
            ["git", "-C", str(self._root), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True, text=True
        )
        return result.stdout.strip() or None

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
        if any(path.name == INDEX_NAME for path in change.writes):
            raise Refused(f"{INDEX_NAME} is reserved for folder indexes.")
        memories = [*change.writes, *change.deletes]
        # Deepest first, so a folder's index is written after the folders inside it.
        folders = sorted({f for path in memories for f in path.parents}, key=lambda f: len(f.parts), reverse=True)
        if not folders:
            return
        touched = [*memories, *(folder / INDEX_NAME for folder in folders)]
        before = {path: self._previous(team, path) for path in touched}
        created = [folder for folder in folders if not self._file(team, folder).is_dir()]
        head = self._head()
        staged = False
        try:
            for path, memory in change.writes.items():
                write_whole(self._file(team, path), memory.to_text())
            for path in change.deletes:
                file = self._file(team, path)
                _settled(lambda: file.unlink(missing_ok=True))
            for folder in folders:
                self._write_index(team, folder)
            with ExitStack() as listening:
                for listener in self._listeners:
                    listening.enter_context(listener.on_change(team, dict(change.writes), set(change.deletes)))
                staged = True
                self._commit(team, touched, change.message, committer)
                for action in change.alongside:
                    action()
        except Exception as error:
            self._undo(team, before, created, head, git_reached=staged)
            if isinstance(error, Refused):
                raise
            log.exception("A save to %s failed and was undone", team)
            raise Refused(
                f"The memory was not saved: {_reason(error)}. Everything is as it was before this save; "
                "try again once that is fixed."
            ) from error

    def _previous(self, team: str, path: PurePosixPath) -> str | None:
        try:
            return read_whole(self._file(team, path))
        except FileNotFoundError:
            return None

    def _commit(self, team: str, touched: list[PurePosixPath], message: str, committer: Committer) -> None:
        """Commit exactly the files this save touched: never a stray file in the folder, nor one staged before it."""
        paths = [f"{team}/{path}" for path in touched]
        self._git("update-index", "--add", "--remove", "--", *paths)
        # Without renames, so a moved memory is named at both its old path and its new one.
        staged = self._git("diff", "--cached", "--name-only", "--no-renames", "-z", "--", *paths)
        changed = [path for path in staged.split("\0") if path]
        if changed:
            trailer = f"\n\nCoding-Agent: {committer.agent}" if committer.agent else ""
            self._git("commit", "-q", "--only", "-m", message + trailer, "--", *changed, committer=committer)

    def _undo(
        self,
        team: str,
        before: dict[PurePosixPath, str | None],
        created: list[PurePosixPath],
        head: str | None,
        *,
        git_reached: bool,
    ) -> None:
        """Put back what a failed save did: the files it touched as `before` holds them, the folders it created, and,
        once it reached git, the branch at `head` with nothing of it staged.

        Every step is tried even when one before it fails, and a failed step is logged: a failure that stopped the
        save partway also stopped it from doing what the step would undo.
        """

        def attempt(what: str, step: Callable[[], object]) -> None:
            try:
                step()
            except Exception:
                log.exception("Undoing a failed save to %s: could not %s", team, what)

        if git_reached:
            paths = [f"{team}/{path}" for path in before]
            if self._head() != head:
                if head is None:
                    attempt("take back the first commit", lambda: self._git("update-ref", "-d", "HEAD"))
                else:
                    attempt("take back the commit", lambda: self._git("update-ref", "HEAD", head))
            if head is None:
                attempt("unstage", lambda: self._git("rm", "--cached", "-q", "--ignore-unmatch", "--", *paths))
            else:
                attempt("unstage", lambda: self._git("reset", "-q", "--", *paths))
        for path, text in before.items():
            file = self._file(team, path)
            if text is None:
                attempt(f"remove {path}", lambda: _settled(lambda: file.unlink(missing_ok=True)))
            else:
                attempt(f"restore {path}", lambda: write_whole(file, text))
        for folder in created:  # deepest first
            directory = self._file(team, folder)
            if directory.is_dir() and not any(directory.iterdir()):
                attempt(f"remove {folder}", lambda: _settled(directory.rmdir))

    def subscribe(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def teams(self) -> list[str]:
        return sorted(d.name for d in self._root.iterdir() if d.is_dir() and not d.name.startswith("."))
