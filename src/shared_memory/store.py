"""The memory folder: memory files on disk, the source of truth, with every change committed to git (ADR-0002, ADR-0003).

This writes and reads the files as they stand now. What they said before is `history.py`, which answers by parsing
git's output rather than by touching the filesystem.

Saves take turns: one change to the memory folder is applied and committed at a time, and whatever a save reads to
decide what it writes, it reads through its `Change`, inside that same turn. A file is written beside its place and
renamed into it, so a reader sees the old file or the new one, never part of one. Reads outside a save don't wait
for their turn: a listing skips a memory deleted while it was being listed.

A save lands whole or not at all. Its files are written, then its listeners (the search index, pins) do their part in
transactions left open, then its commit is built in memory with pygit2 from exactly the files the save touched and
main is moved to it, then whatever else the save asked for (its audit entry) runs, and only then do the listeners'
transactions commit. Moving main is the save's last git step. A failure before it leaves main untouched; a failure
after it is put back by a revert commit, never by resetting main. Either way the transactions roll back and every file
the save touched is put back as it was, so nothing is left on disk for the next save to commit under another member's
name. Saves don't use git's index file and don't keep it up to date: compare the files with main's tree, not the index.

A memory file is parsed once and kept until it changes: each read looks at the file on disk and parses it again only
if it is a different file, or was modified or resized, since it was parsed, so a file changed outside the server is
still noticed. Every save also drops what it changed.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol, TypeVar

import pygit2
import pygit2.enums

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


def _reason(error: Exception) -> str:
    """Why a save failed, in one line."""
    lines = str(error).strip().splitlines()
    reason = lines[0] if lines else type(error).__name__
    if isinstance(error, pygit2.GitError):
        return f"git could not record it ({reason})"
    return reason


# Committing to main. A save builds its commit in memory on top of main and moves main to it with a compare-and-swap;
# if main moved meanwhile, it builds again on the new main. Paths saved in the same moment never overlap, so building
# again can't conflict.

MAIN = "refs/heads/main"
SERVER = ("Shared Memory", "server@shared-memory.invalid")
# libgit2 has no compare-and-swap on a ref, and only this process saves, so reading main, checking it and moving it
# happen under one lock. Held only for that, never while a commit is built.
_moving_main = threading.Lock()
_EMPTY_TREE = pygit2.Oid(hex="4b825dc642cb6eb9a060e54bf8d69288fbee4904")


@dataclass(frozen=True)
class _Landed:
    """A save's commit that main was moved to, and the commit it was built on."""

    commit: pygit2.Oid
    parent: pygit2.Oid | None


def _author(committer: Committer) -> pygit2.Signature:
    return pygit2.Signature(committer.name, f"{committer.member_id}@members.shared-memory.invalid")


def _cleaned(message: str) -> str:
    """A commit message as `git commit -m` leaves it: no trailing spaces, no blank lines at the ends, one newline."""
    lines = [line.rstrip() for line in message.splitlines()]
    return "\n".join(lines).strip("\n") + "\n"


def _main(repository: pygit2.Repository) -> pygit2.Oid | None:
    reference = repository.references.get(MAIN)
    if reference is None:
        return None
    target = reference.target
    assert isinstance(target, pygit2.Oid)  # main names a commit, never another ref
    return target


def _move_main(repository: pygit2.Repository, expected: pygit2.Oid | None, commit: pygit2.Oid, why: str) -> bool:
    """Move main to a commit only if it is still at the commit that was built on. False when it moved first."""
    with _moving_main:
        if _main(repository) != expected:
            return False
        repository.create_reference_direct(MAIN, commit, expected is not None, message=why)
        return True


def _tree(
    repository: pygit2.Repository, base: pygit2.Tree | None, changes: dict[tuple[str, ...], pygit2.Oid | None]
) -> pygit2.Oid | None:
    """A tree with changes (a file's blob, or None to remove it) applied on top of base. None when it holds nothing."""
    builder = repository.TreeBuilder(base) if base is not None else repository.TreeBuilder()
    below: dict[str, dict[tuple[str, ...], pygit2.Oid | None]] = {}
    for parts, blob in changes.items():
        if len(parts) > 1:
            below.setdefault(parts[0], {})[parts[1:]] = blob
        elif blob is not None:
            builder.insert(parts[0], blob, pygit2.enums.FileMode.BLOB)
        elif builder.get(parts[0]) is not None:
            builder.remove(parts[0])
    for name, inside in below.items():
        entry = base[name] if base is not None and name in base else None
        subtree = repository[entry.id] if entry is not None and entry.type == pygit2.enums.ObjectType.TREE else None
        assert subtree is None or isinstance(subtree, pygit2.Tree)
        built = _tree(repository, subtree, inside)
        if built is not None:
            builder.insert(name, built, pygit2.enums.FileMode.TREE)
        elif builder.get(name) is not None:
            builder.remove(name)  # a folder left empty goes, as git keeps no empty folders
    return builder.write() if len(builder) else None


def _land(
    repository: pygit2.Repository, files: dict[str, pygit2.Oid | None], message: str, author: pygit2.Signature
) -> _Landed | None:
    """Commit files (each a blob, or None where there is no file) on top of main and move main to it.

    Built again on the new main whenever main moved first. None when main already holds the files as they are.
    """
    changes = {tuple(path.split("/")): blob for path, blob in files.items()}
    while True:
        parent = _main(repository)
        base = repository[parent].peel(pygit2.Tree) if parent is not None else None
        tree = _tree(repository, base, changes) or repository.TreeBuilder().write()
        if tree == (base.id if base is not None else _EMPTY_TREE):
            return None
        commit = repository.create_commit(
            None, author, pygit2.Signature(*SERVER), message, tree, [parent] if parent is not None else []
        )
        if _move_main(repository, parent, commit, f"commit: {message.splitlines()[0]}"):
            return _Landed(commit, parent)


def _revert(repository: pygit2.Repository, paths: list[str], landed: _Landed) -> None:
    """Put back what a commit on main changed at paths with a new commit on top of main: main only ever moves on."""
    base = repository[landed.parent].peel(pygit2.Tree) if landed.parent is not None else None
    files: dict[str, pygit2.Oid | None] = {}
    for path in paths:
        entry = base[path] if base is not None and path in base else None
        files[path] = entry.id if entry is not None and entry.type == pygit2.enums.ObjectType.BLOB else None
    subject = repository[landed.commit].peel(pygit2.Commit).message.splitlines()[0]
    message = f'Revert "{subject}"\n\nThis reverts commit {landed.commit}: the save failed after it was committed.\n'
    _land(repository, files, message, pygit2.Signature(*SERVER))


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


# Which file is at a path and how it stands: a save renames a new file in, and an edit in place changes when the file
# was modified or how long it is.
_Stamp = tuple[int, int, int]


def _stamp(status: os.stat_result) -> _Stamp:
    return status.st_ino, status.st_mtime_ns, status.st_size


def _read_stamped(file: Path) -> tuple[str, _Stamp]:
    """A file's text and its stamp, both taken from the one open file."""
    with file.open(encoding="utf-8") as opened:
        return opened.read(), _stamp(os.fstat(opened.fileno()))


@dataclass(frozen=True)
class _Parsed:
    stamp: _Stamp
    memory: Memory
    size: int


class ParsedMemories:
    """Memory files already parsed, dropping the least recently read beyond a bound on the text they were parsed from.

    Thread-safe. A file read while a save ended isn't kept, since a save can leave a file stamped as it
    was before.
    """

    def __init__(self, bound: int) -> None:
        self._bound = bound
        self._size = 0
        self._parsed: OrderedDict[Path, _Parsed] = OrderedDict()
        self._saves = 0
        self._guard = threading.Lock()

    def read(self, file: Path) -> Memory:
        """What a memory file says: FileNotFoundError when there is none, Refused when it isn't a memory.

        The memory returned is a copy of its own, for the caller to change freely.
        """
        status = _settled(lambda: os.stat(file))
        if stat.S_ISDIR(status.st_mode):
            raise FileNotFoundError(file)
        with self._guard:
            parsed = self._parsed.get(file)
            if parsed is not None and parsed.stamp == _stamp(status):
                self._parsed.move_to_end(file)
                return _copy(parsed.memory)
            saves = self._saves
        text, stamp = _settled(lambda: _read_stamped(file))
        memory = Memory.from_text(text)
        with self._guard:
            if saves == self._saves:
                self._keep(file, _Parsed(stamp, memory, len(text)))
        return _copy(memory)

    def forget(self, files: Iterable[Path]) -> None:
        """Drop what a save changed, whether it landed or was undone, and keep nothing read before it ended."""
        with self._guard:
            self._saves += 1
            for file in files:
                self._drop(file)

    def _keep(self, file: Path, parsed: _Parsed) -> None:
        self._drop(file)
        if parsed.size > self._bound:
            return
        self._parsed[file] = parsed
        self._size += parsed.size
        while self._size > self._bound:
            self._drop(next(iter(self._parsed)))

    def _drop(self, file: Path) -> None:
        dropped = self._parsed.pop(file, None)
        if dropped is not None:
            self._size -= dropped.size


def _copy(memory: Memory) -> Memory:
    return replace(memory, related_files=list(memory.related_files))


# How much memory text the server keeps parsed, in characters: a large team's whole memory, several times over.
PARSED_CHARACTERS = 32 * 1024 * 1024


class MemoryStore:
    def __init__(
        self, root: Path, listeners: Iterable[ChangeListener] = (), parsed_characters: int = PARSED_CHARACTERS
    ) -> None:
        self._root = root.resolve()
        self._parsed = ParsedMemories(parsed_characters)
        self._root.mkdir(parents=True, exist_ok=True)
        self._turn = threading.Lock()
        self._listeners = list(listeners)
        if not (self._root / ".git").exists():
            repository = pygit2.init_repository(str(self._root), initial_head="main")
            # For the git CLI that reads history and takes the backup.
            repository.config["core.autocrlf"] = "false"
            repository.config["core.quotepath"] = "false"

    def _file(self, team: str, path: PurePosixPath) -> Path:
        return confine(self._root, team, path)

    def exists(self, team: str, path: PurePosixPath) -> bool:
        return self._file(team, path).is_file()

    def list_folder(
        self, team: str, folder: PurePosixPath
    ) -> tuple[list[tuple[PurePosixPath, Memory]], list[PurePosixPath]]:
        """The memories directly in a folder (sorted by title) and its subfolders."""
        directory = self._file(team, folder)
        try:
            with os.scandir(directory) as listing:
                entries = [(entry.name, entry.is_dir()) for entry in listing]
        except (FileNotFoundError, NotADirectoryError):
            return [], []
        memories: list[tuple[PurePosixPath, Memory]] = []
        folders: list[PurePosixPath] = []
        for name, is_folder in entries:
            if name.startswith("."):
                continue
            if is_folder:
                folders.append(folder / name)
            elif name.endswith(".md") and name != INDEX_NAME:
                try:
                    memories.append((folder / name, self._parsed.read(directory / name)))
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

    def _write_index(self, team: str, folder: PurePosixPath) -> bool:
        """Bring a folder's index up to date, touching the file only when its text changes.

        Returns whether the folder still exists afterwards: an emptied folder loses its index and is removed.
        """
        directory = self._file(team, folder)
        index = directory / INDEX_NAME
        memories, folders = self.list_folder(team, folder)
        if not memories and not folders:
            _settled(lambda: index.unlink(missing_ok=True))
            if folder.parts and directory.is_dir() and not any(directory.iterdir()):
                _settled(directory.rmdir)
            return directory.is_dir()
        lines = [f"# {folder if folder.parts else 'Memory'}", ""]
        if memories:
            lines += ["## Memories", ""]
            lines += [f"- [{memory.title}]({path.name}): {memory.summary}" for path, memory in memories]
            lines.append("")
        if folders:
            lines += ["## Folders", ""]
            lines += [f"- [{sub.name}/]({sub.name}/{INDEX_NAME})" for sub in folders]
            lines.append("")
        text = "\n".join(lines)
        try:
            unchanged = read_whole(index) == text
        except FileNotFoundError:
            unchanged = False
        if not unchanged:
            write_whole(index, text)
        return True

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
        try:
            return self._parsed.read(self._file(team, path))
        except FileNotFoundError:
            raise Refused(f"There is no memory at {str(path)!r}.") from None

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
            try:
                yield change
                self._apply(change, committer)
            finally:
                # Whether the save landed or was undone, what it touched is read again.
                self._parsed.forget(self._file(team, path) for path in [*change.writes, *change.deletes])

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
        repository = self._repository()
        landed: _Landed | None = None
        try:
            for path, memory in change.writes.items():
                write_whole(self._file(team, path), memory.to_text())
            for path in change.deletes:
                file = self._file(team, path)
                _settled(lambda: file.unlink(missing_ok=True))
            # A folder's index lists its memories and its subfolders' names, so a parent's listing changes only when
            # a folder under it appeared or disappeared.
            pending = {path.parent for path in memories}
            for folder in folders:
                if folder not in pending:
                    continue
                exists = self._write_index(team, folder)
                if exists == (folder in created) and folder.parts:
                    pending.add(folder.parent)
            with ExitStack() as listening:
                for listener in self._listeners:
                    listening.enter_context(listener.on_change(team, dict(change.writes), set(change.deletes)))
                # Moving main is the save's last git step: every failure before it leaves main untouched.
                landed = self._commit(repository, team, touched, change.message, committer)
                for action in change.alongside:
                    action()
            # Leaving the block committed the listeners' transactions.
        except Exception as error:
            self._undo(repository, team, before, created, landed)
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

    def _repository(self) -> pygit2.Repository:
        """The memory folder's repository, opened for one save: libgit2's objects aren't shared between threads."""
        return pygit2.Repository(str(self._root))

    def _commit(
        self,
        repository: pygit2.Repository,
        team: str,
        touched: list[PurePosixPath],
        message: str,
        committer: Committer,
    ) -> _Landed | None:
        """Commit exactly the files this save touched, as they are on disk, on top of main, and move main to it.

        The commit is built in memory: never a stray file in the folder, nor anything left in git's index, which
        saves don't use. None when the files already stand in main as they are.
        """
        blobs: dict[str, pygit2.Oid | None] = {}
        for path in touched:
            file = self._file(team, path)
            blobs[f"{team}/{path}"] = repository.create_blob(file.read_bytes()) if file.is_file() else None
        trailer = f"\n\nCoding-Agent: {committer.agent}" if committer.agent else ""
        return _land(repository, blobs, _cleaned(message + trailer), _author(committer))

    def _undo(
        self,
        repository: pygit2.Repository,
        team: str,
        before: dict[PurePosixPath, str | None],
        created: list[PurePosixPath],
        landed: _Landed | None,
    ) -> None:
        """Put back what a failed save did: the files it touched as `before` holds them, the folders it created, and,
        once it moved main, a revert commit on main putting back what its commit changed. main is never reset.

        Every step is tried even when one before it fails, and a failed step is logged: a failure that stopped the
        save partway also stopped it from doing what the step would undo.
        """

        def attempt(what: str, step: Callable[[], object]) -> None:
            try:
                step()
            except Exception:
                log.exception("Undoing a failed save to %s: could not %s", team, what)

        if landed is not None:
            attempt("revert its commit", lambda: _revert(repository, [f"{team}/{path}" for path in before], landed))
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
