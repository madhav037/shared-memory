"""The memory folder: memory files on disk, the source of truth, with every change committed to git (ADR-0002, ADR-0003).

This writes and reads the files as they stand now. What they said before is `history.py`, which answers by parsing
git's output rather than by touching the filesystem.

Saves take turns per area (ADR-0012): a save declares the areas it changes, waits for their turns, and whatever it
reads to decide what it writes, it reads through its `Change`, inside those same turns. Saves in different areas run
at once: each commits only the files it changed, and a folder's index only when its listing changed. A file is written
beside its place and renamed into it, so a reader sees the old file or the new one, never part of one. Reads outside a
save don't wait for a turn: a listing skips a memory deleted while it was being listed.

A save lands whole or not at all. Its files are written, then its listeners (the search index, pins) do their part in
one database transaction left open, then its commit is built in memory with pygit2 from exactly the files the save touched and
main is moved to it, then whatever else the save asked for (its audit entry) runs in that transaction, and only then
does it commit. Moving main is the save's last git step. A failure before it leaves main untouched; a failure
after it is put back by a revert commit, never by resetting main. Either way the transaction rolls back and every file
the save changed is put back as it was, and nothing else: nothing is left on disk for the next save to commit under
another member's name, and no other area's save is undone. Saves don't use git's index file and don't keep it up to
date: compare the files with main's tree, not the index.

A memory file is parsed once and kept until it changes: each read looks at the file on disk and parses it again only
if it is a different file, or was modified or resized, since it was parsed, so a file changed outside the server is
still noticed. Every save also drops what it changed.
"""

from __future__ import annotations

import itertools
import logging
import os
import stat
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol, TypeVar

import pygit2
import pygit2.enums

from shared_memory.errors import Refused
from shared_memory.memory import INDEX_NAME, Area, Memory, area_of, slugify

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
    # The areas the save declared before taking their turns: it writes and deletes only inside them.
    areas: frozenset[Area]
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
        self._inside_its_areas(path)
        self.deletes.discard(path)
        self.writes[path] = memory

    def delete(self, path: PurePosixPath) -> None:
        self._inside_its_areas(path)
        self.writes.pop(path, None)
        self.deletes.add(path)

    def _inside_its_areas(self, path: PurePosixPath) -> None:
        """A save changing memory outside the areas whose turns it took is a bug in the save, never the member's."""
        if area_of(path) not in self.areas:
            raise AssertionError(f"{path} is outside the areas this save took turns for: declare its area.")

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
    for attempt in range(5):
        target = (team_dir / Path(*path.parts)).resolve() if path.parts else team_dir
        if target == team_dir or team_dir in target.parents:
            return target
        # On Windows a path resolved while another area's save creates or removes a folder on it can come back
        # wrong for a moment (#146); saves in different areas now do that at once, so look again before refusing.
        if sys.platform != "win32" or attempt == 4:
            break
        time.sleep(0.01)
    raise Refused(f"{str(path)!r} is outside your team's memory.")


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

    Thread-safe. A file read while a save that changed it ended isn't kept, since a save can leave a file stamped as it
    was before. Saves in other areas end many times a second, so a save that changed other files doesn't count.
    """

    def __init__(self, bound: int) -> None:
        self._bound = bound
        self._size = 0
        self._parsed: OrderedDict[Path, _Parsed] = OrderedDict()
        self._saves = 0
        # The files of the last saves to end, oldest first; a read that spans more saves than this keeps nothing.
        self._ended: deque[frozenset[Path]] = deque(maxlen=RECENT_SAVES)
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
            if self._unchanged_since(saves, file):
                self._keep(file, _Parsed(stamp, memory, len(text)))
        return _copy(memory)

    def forget(self, files: Iterable[Path]) -> None:
        """Drop what a save changed, whether it landed or was undone, and keep none of it read before it ended."""
        changed = frozenset(files)
        with self._guard:
            self._saves += 1
            self._ended.append(changed)
            for file in changed:
                self._drop(file)

    def _unchanged_since(self, saves: int, file: Path) -> bool:
        """Whether no save that ended after the first `saves` changed this file."""
        since = self._saves - saves
        if since > len(self._ended):
            return False
        return not any(file in changed for changed in itertools.islice(reversed(self._ended), since))

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


class Turns:
    """The one place saves are ordered (ADR-0012). Only this process saves, so mutexes between its threads are enough;
    several servers would hold these turns somewhere they all share, and only this class would change.

    A save takes the turn of every area it declared, in one fixed order (team, then project memory, then personal
    memory, each by id), so two saves touching the same areas can't each hold one the other waits for. The folders
    above the areas (the team's own folder, `projects/`, a project's folder and its `people/`) are shared by areas; a
    save that creates or removes a folder directly under one of them also takes that team's shared folders' turn,
    always last, so it is never held while an area's turn is awaited.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._areas: dict[tuple[str, Area], threading.Lock] = {}
        self._shared_folders: dict[str, threading.Lock] = {}

    def _mutex(self, mutexes: dict[T, threading.Lock], key: T) -> threading.Lock:
        with self._guard:
            return mutexes.setdefault(key, threading.Lock())

    @contextmanager
    def areas(self, team: str, areas: Iterable[Area]) -> Iterator[None]:
        with ExitStack() as held:
            for area in sorted(set(areas), key=Area.order):
                held.enter_context(self._mutex(self._areas, (team, area)))
            yield

    @contextmanager
    def shared_folders(self, team: str) -> Iterator[None]:
        with self._mutex(self._shared_folders, team):
            yield


# How much memory text the server keeps parsed, in characters: a large team's whole memory, several times over.
PARSED_CHARACTERS = 32 * 1024 * 1024
# How many of the last saves' changed files the parsed memories remember, to tell which reads a save made stale.
RECENT_SAVES = 1024


class MemoryStore:
    def __init__(
        self,
        root: Path,
        listeners: Iterable[ChangeListener] = (),
        parsed_characters: int = PARSED_CHARACTERS,
        transaction: Callable[[], AbstractContextManager[object]] = nullcontext,
    ) -> None:
        """transaction, when given, holds all of one save's listeners and actions in one database transaction."""
        self._root = root.resolve()
        self._transaction = transaction
        self._parsed = ParsedMemories(parsed_characters)
        self._root.mkdir(parents=True, exist_ok=True)
        self._turns = Turns()
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

    def _write_index(self, team: str, folder: PurePosixPath, before: dict[PurePosixPath, str | None]) -> bool:
        """Bring a folder's index up to date, touching the file only when its text changes, and noting in `before`
        what it held before this save first changed it.

        Returns whether the folder still exists afterwards: an emptied folder loses its index and is removed.
        """
        directory = self._file(team, folder)
        index = directory / INDEX_NAME
        memories, folders = self.list_folder(team, folder)
        try:
            previous: str | None = read_whole(index)
        except FileNotFoundError:
            previous = None
        if not memories and not folders:
            if previous is not None:
                before.setdefault(folder / INDEX_NAME, previous)
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
        if previous != text:
            before.setdefault(folder / INDEX_NAME, previous)
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
    def _take_turns(self, team: str, areas: Iterable[Area]) -> Iterator[None]:
        """Wait for the turns of a save's areas. Saves are ordered only here and in `_shared_folders_turn`, both
        through `Turns`."""
        with self._turns.areas(team, areas):
            yield

    def _shared_folders_turn(self, team: str) -> AbstractContextManager[None]:
        return self._turns.shared_folders(team)

    @contextmanager
    def change(
        self, team: str, committer: Committer, message: str = "", *, areas: Iterable[Area]
    ) -> Iterator[Change]:
        """One save, in the turns of the areas it declares: read what it changes and write through the Change, and it
        lands as one commit. The areas are every area the save reads to change or writes; writing outside them is a
        bug and fails loudly.

        A refusal inside the block leaves the memory folder as it was.
        """
        declared = frozenset(areas)
        with self._take_turns(team, declared):
            change = Change(self, team, message, declared)
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
        with ExitStack() as turns:
            shared = self._reshapes_shared_folders(change)
            if shared:
                # Held until the save has landed or been undone, so no other save lists these folders in between.
                turns.enter_context(self._shared_folders_turn(team))
            # What each file this save changes held before it: its memories now, each index as the save changes it.
            # Only these are committed and, if the save fails, put back, so no other area's change is ever undone.
            before = {path: self._previous(team, path) for path in memories}
            created = [folder for folder in folders if not self._file(team, folder).is_dir()]
            repository = self._repository()
            landed: _Landed | None = None
            try:
                for path, memory in change.writes.items():
                    write_whole(self._file(team, path), memory.to_text())
                for path in change.deletes:
                    file = self._file(team, path)
                    _settled(lambda: file.unlink(missing_ok=True))
                # A folder's index lists its memories and its subfolders' names, so a parent's listing changes only
                # when a folder under it appeared or disappeared.
                pending = {path.parent for path in memories}
                for folder in folders:
                    if folder not in pending:
                        continue
                    if not shared and area_of(folder) not in change.areas:
                        raise AssertionError(f"{folder} is shared by areas, and this save didn't take its turn.")
                    exists = self._write_index(team, folder, before)
                    if exists == (folder in created) and folder.parts:
                        pending.add(folder.parent)
                with self._transaction(), ExitStack() as listening:
                    for listener in self._listeners:
                        listening.enter_context(listener.on_change(team, dict(change.writes), set(change.deletes)))
                    # Moving main is the save's last git step: every failure before it leaves main untouched.
                    landed = self._commit(repository, team, list(before), change.message, committer)
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

    def _reshapes_shared_folders(self, change: Change) -> bool:
        """Whether the save creates or removes an area's own folder, changing the listing of a folder areas share.

        Decided before anything is written: an area's folder holds only that area's memories, so while the save holds
        its areas' turns nothing else can create, fill or empty it.
        """
        for path in change.writes:
            area = area_of(path)
            assert area is not None
            if not self._file(change.team, area.folder).is_dir():
                return True
        emptied = {area.folder for area in map(area_of, change.deletes) if area is not None}
        return any(not self._holds_memories_after(change, folder) for folder in emptied)

    def _holds_memories_after(self, change: Change, folder: PurePosixPath) -> bool:
        """Whether any memory is left in a folder, at any depth, once the save's writes and deletes are done."""
        if any(folder in path.parents for path in change.writes):
            return True
        directory = self._file(change.team, folder)
        for below, _, names in os.walk(directory):
            for name in names:
                if name.startswith(".") or not name.endswith(".md") or name == INDEX_NAME:
                    continue
                path = folder / Path(below, name).relative_to(directory).as_posix()
                if path not in change.deletes:
                    return True
        return False
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
