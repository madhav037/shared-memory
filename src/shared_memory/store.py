"""The memory folder: memory files on disk, the source of truth, with every change committed to git (ADR-0002, ADR-0003).

This writes and reads the files as they stand now. What they said before is `history.py`, which answers by parsing
git's output rather than by touching the filesystem.

Saves take turns per area (ADR-0012), held in Postgres so every worker saving to the folder sees them (ADR-0013): a
save declares the areas it changes, waits for their turns, and whatever it reads to decide what it writes, it reads
through its `Change`, inside those same turns. Saves in different areas run at once: each commits only the files it
changed, and a folder's index only when its listing changed. A file is written beside its place and renamed into it,
so a reader sees the old file or the new one, never part of one. Reads outside a save don't wait for a turn: a listing
skips a memory deleted while it was being listed.

A save lands whole or not at all. Its files are written, then its listeners (the search index, pins) do their part in
one database transaction left open, then its commit is built in memory with pygit2 from exactly the files the save touched and
main is moved to it, then whatever else the save asked for (its audit entry) runs in that transaction, and only then
does it commit. Moving main is the save's last git step. A failure before it leaves main untouched; a failure
after it is put back by a revert commit, never by resetting main. Either way the transaction rolls back and every file
the save changed is put back as it was, and nothing else: nothing is left on disk for the next save to commit under
another member's name, and no other area's save is undone. Saves don't use git's index file and don't keep it up to
date: compare the files with main's tree, not the index.

A save cut off without being undone, by its worker dying, is put back by the next save to take its turn: before writing
any file a save records a marker of the paths it may touch, committed apart from its own transaction, and clears it as
it lands or once it is undone. A marker found under a turn just taken names paths to put back to what main holds.

A memory file is parsed once and kept until it changes: each read looks at the file on disk and parses it again only
if it is a different file, or was modified or resized, since it was parsed, so a file changed outside the server is
still noticed. Every save also drops what it changed.
"""

from __future__ import annotations

import functools
import hashlib
import itertools
import logging
import os
import stat
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
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


MovingMain = Callable[[], AbstractContextManager[None]]


def _move_main(
    repository: pygit2.Repository, expected: pygit2.Oid | None, commit: pygit2.Oid, why: str, moving_main: MovingMain
) -> bool:
    """Move main to a commit only if it is still at the commit that was built on. False when it moved first.

    libgit2 has no compare-and-swap on a ref, so reading main, checking it and moving it happen in the save's turn to
    move main, which every worker's saves share (`Turns.moving_main`). Held only for that, never while a commit is
    built.
    """
    with moving_main():
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
    repository: pygit2.Repository,
    files: dict[str, pygit2.Oid | None],
    message: str,
    author: pygit2.Signature,
    moving_main: MovingMain,
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
        if _move_main(repository, parent, commit, f"commit: {message.splitlines()[0]}", moving_main):
            return _Landed(commit, parent)


def _revert(repository: pygit2.Repository, paths: list[str], landed: _Landed, moving_main: MovingMain) -> None:
    """Put back what a commit on main changed at paths with a new commit on top of main: main only ever moves on."""
    base = repository[landed.parent].peel(pygit2.Tree) if landed.parent is not None else None
    files: dict[str, pygit2.Oid | None] = {}
    for path in paths:
        entry = base[path] if base is not None and path in base else None
        files[path] = entry.id if entry is not None and entry.type == pygit2.enums.ObjectType.BLOB else None
    subject = repository[landed.commit].peel(pygit2.Commit).message.splitlines()[0]
    message = f'Revert "{subject}"\n\nThis reverts commit {landed.commit}: the save failed after it was committed.\n'
    _land(repository, files, message, pygit2.Signature(*SERVER), moving_main)


def memory_folder(root: Path) -> Path:
    """The memory folder as the server reaches every file in it, the one place its path on disk is decided.

    On Windows an ordinary path stops working past 260 characters, which a memory under a topic in a deep memory
    folder passes (#140), so there it is the extended-length form (`\\\\?\\C:\\...`), which has no such limit.
    Everywhere else it is the resolved path. Memory paths, relative to a team's folder, are the same either way.
    """
    resolved = root.resolve()
    if sys.platform != "win32":
        return resolved
    text = str(resolved)
    if text.startswith("\\\\?\\"):
        return resolved
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def ordinary(folder: Path) -> str:
    """A folder's path as programs other than this server take it, such as the git CLI: without the
    extended-length form `memory_folder` gives it on Windows."""
    text = str(folder)
    if sys.platform != "win32" or not text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    return text[4:]


@functools.cache
def _team_folder(root: Path, team: str) -> Path:
    return (root / team).resolve()


# Folders under a team's folder already seen to be plain folders, not links. A folder only becomes a link if someone
# with the server's disk replaces it, and they could change anything.
_plain_folders: set[Path] = set()


def confine(root: Path, team: str, path: PurePosixPath) -> Path:
    """Where a memory path lands on disk, refusing anything that would leave the team's own folder.

    The memory folder holds only what the server wrote, so nothing in it is a link: a path is refused when it names
    `..`, or when a folder on the way or the file itself is a link. Checked by name and one `lstat` per folder not
    seen before, not by resolving the path, which costs a lookup per part on every call and, on Windows, can come back
    wrong while another save creates or removes a folder on the way (#146).
    """
    team_dir = _team_folder(root, team)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise Refused(f"{str(path)!r} is outside your team's memory.")
    target = team_dir.joinpath(*path.parts)
    folder = team_dir
    for part in path.parts:
        folder = folder / part
        if folder in _plain_folders:
            continue
        try:
            if stat.S_ISLNK(os.lstat(folder).st_mode):
                raise Refused(f"{str(path)!r} is outside your team's memory.")
        except FileNotFoundError:
            break  # nothing from here on exists yet, so nothing can link out
        if folder != target:
            _plain_folders.add(folder)
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


class SaveTransaction(Protocol):
    """One save's database transaction, which holds its turns (`db.SaveTransaction`)."""

    def hold(self, key: int) -> None:
        """Wait for a lock, and hold it until the save's transaction ends."""
        ...

    def briefly(self, key: int) -> AbstractContextManager[None]:
        """Wait for a lock, and hold it only for the block."""
        ...

    def left_behind(self, turns: Sequence[int]) -> dict[int, list[str]]:
        """The paths named by markers other saves left under these turns."""
        ...

    def mark(self, team: str, paths: dict[int, list[str]]) -> None:
        """Record under each turn the paths this save may touch there, committed before it writes any."""
        ...

    def unmark(self) -> None:
        """Clear this save's markers once it has been undone."""
        ...

    def apart(self, turns: Sequence[int]) -> AbstractContextManager[None]:
        """Database work committed on its own, with the markers left under these turns cleared."""
        ...

    def commit(self) -> None:
        """Commit the save's database work and clear its markers; the locks it holds until then are released."""
        ...


class OneProcess:
    """Saves' transactions for a store with no database, such as one a command only reads through: its turns are
    mutexes between this process's threads, and it has no database work to commit."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[int, threading.RLock] = {}

    def lock(self, key: int) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())

    @contextmanager
    def __call__(self) -> Iterator[SaveTransaction]:
        transaction = _OneProcessTransaction(self)
        try:
            yield transaction
        finally:
            for lock in reversed(transaction.held):
                lock.release()


class _OneProcessTransaction:
    def __init__(self, locks: OneProcess) -> None:
        self._locks = locks
        self.held: list[threading.RLock] = []

    def hold(self, key: int) -> None:
        lock = self._locks.lock(key)
        lock.acquire()
        self.held.append(lock)

    @contextmanager
    def briefly(self, key: int) -> Iterator[None]:
        with self._locks.lock(key):
            yield

    # With no database there are no markers: a save cut off here was cut off with the whole process.

    def left_behind(self, turns: Sequence[int]) -> dict[int, list[str]]:
        return {}

    def mark(self, team: str, paths: dict[int, list[str]]) -> None:
        pass

    def unmark(self) -> None:
        pass

    @contextmanager
    def apart(self, turns: Sequence[int]) -> Iterator[None]:
        yield

    def commit(self) -> None:
        pass


def _lock_key(*names: str) -> int:
    """A Postgres advisory lock's key: a signed 64-bit number derived from names, the same in every worker."""
    digest = hashlib.blake2b("\0".join(("shared-memory", *names)).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


_MOVING_MAIN = _lock_key("moving main")


class Turns:
    """The one place saves are ordered (ADR-0012, ADR-0013). A turn is a Postgres advisory lock held by the save's own
    transaction, so every worker saving to the memory folder sees it, and a worker that dies releases its turns with
    its connection. Each lock's key is derived from the team and the area, so no two teams' turns are the same lock.

    A save takes the turn of every area it declared at its start, before it reads or writes any file, in one fixed
    order (team, then project memory, then personal memory, each by id), so two saves touching the same areas can't
    each hold one the other waits for. The folders above the areas (the team's own folder, `projects/`, a project's
    folder and its `people/`) are shared by areas; a save that creates or removes a folder directly under one of them
    also takes that team's shared folders' turn, always last, so it is never held while an area's turn is awaited.
    Every turn is held until the save's transaction ends: once it has landed or been undone.

    Moving main has a turn of its own, shared by every save, held only while main is read, checked and moved.
    """

    def areas(self, transaction: SaveTransaction, team: str, areas: Iterable[Area]) -> None:
        for area in sorted(set(areas), key=Area.order):
            transaction.hold(self.area(team, area))

    def shared_folders(self, transaction: SaveTransaction, team: str) -> None:
        transaction.hold(self.shared(team))

    def area(self, team: str, area: Area) -> int:
        """An area's turn, which also names the markers saves leave under it."""
        return _lock_key("area", team, str(area.folder))

    def shared(self, team: str) -> int:
        """The team's shared folders' turn."""
        return _lock_key("shared folders", team)

    def moving_main(self, transaction: SaveTransaction) -> MovingMain:
        return lambda: transaction.briefly(_MOVING_MAIN)


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
        transaction: Callable[[], AbstractContextManager[SaveTransaction]] | None = None,
        sets_up: bool = True,
    ) -> None:
        """transaction opens one save's database transaction, which holds its turns and all of its listeners' and
        actions' work. Without one, turns are taken in this process only and there is no database work to hold.

        sets_up says whether this makes the folder and its git repository when they are missing, or finds them made."""
        self._root = memory_folder(root)
        self._transaction = transaction or OneProcess()
        self._parsed = ParsedMemories(parsed_characters)
        if sets_up:
            self._root.mkdir(parents=True, exist_ok=True)
        self._turns = Turns()
        self._listeners = list(listeners)
        if sets_up and not (self._root / ".git").exists():
            repository = pygit2.init_repository(ordinary(self._root), initial_head="main")
            # For the git CLI that reads history and takes the backup.
            repository.config["core.autocrlf"] = "false"
            repository.config["core.quotepath"] = "false"
            # On Windows git refuses a path past 260 characters without it; elsewhere it changes nothing.
            repository.config["core.longpaths"] = "true"

    def _file(self, team: str, path: PurePosixPath) -> Path:
        return confine(self._root, team, path)

    def exists(self, team: str, path: PurePosixPath) -> bool:
        return self._file(team, path).is_file()

    def list_folder(
        self, team: str, folder: PurePosixPath
    ) -> tuple[list[tuple[PurePosixPath, Memory]], list[PurePosixPath]]:
        """The memories directly in a folder (sorted by title) and its subfolders."""
        return self._list(self._file(team, folder), folder)

    def _list(
        self, directory: Path, folder: PurePosixPath
    ) -> tuple[list[tuple[PurePosixPath, Memory]], list[PurePosixPath]]:
        """list_folder for a folder already confined to its team's memory.

        A subfolder that is a link is left out, so a walk that goes down by these names never leaves the team's folder.
        """
        try:
            with os.scandir(directory) as listing:
                entries = [(entry.name, entry.is_dir(follow_symlinks=False)) for entry in listing]
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
        """Every folder under root, depth first in path order, with the memories directly in it.

        Only root is confined: the folders under it are reached by the names in their parent, never through a link.
        """
        yield from self._walk(self._file(team, root), root)

    def _walk(
        self, directory: Path, folder: PurePosixPath
    ) -> Iterator[tuple[PurePosixPath, list[tuple[PurePosixPath, Memory]]]]:
        memories, folders = self._list(directory, folder)
        yield folder, memories
        for below in folders:
            yield from self._walk(directory / below.name, below)

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
    def _take_turns(self, transaction: SaveTransaction, team: str, areas: Iterable[Area]) -> Iterator[None]:
        """Wait for the turns of a save's areas, held until its transaction ends. Saves are ordered only here and in
        `_shared_folders_turn`, both through `Turns`."""
        self._turns.areas(transaction, team, areas)
        yield

    def _shared_folders_turn(self, transaction: SaveTransaction, team: str) -> None:
        """Take the team's shared folders' turn, first putting back what a save cut off in that turn left."""
        self._turns.shared_folders(transaction, team)
        shared = self._turns.shared(team)
        left = transaction.left_behind([shared])
        if left:
            self._put_back(transaction, team, [shared], left[shared], lambda folder: area_of(folder) is None)

    def _repair_areas(self, transaction: SaveTransaction, team: str, areas: frozenset[Area]) -> None:
        """Put back what a save cut off in these areas' turns left, before this save reads anything in them.

        A save clears its markers before its turns are released, so a marker found under a turn just taken was left
        by a save cut off mid-turn: a worker that died, whose connection closing released its turns. Its files may be
        on disk uncommitted, or committed to main while its search index rows never were; putting its paths back to
        what main holds, and indexing them again, covers both. One lookup, of these turns' and the team's shared
        folders' markers, when there is nothing to put back.
        """
        turns = [self._turns.area(team, area) for area in areas]
        shared = self._turns.shared(team)
        left = transaction.left_behind([*turns, shared])
        paths = [path for turn in turns for path in left.get(turn, [])]
        if not paths:
            return
        self._put_back(transaction, team, turns, paths, lambda folder: area_of(folder) in areas)
        if shared in left:
            # The cut-off save also changed the folders its areas share; their turn comes last, so it can be taken now.
            self._shared_folders_turn(transaction, team)
        gone = [area.folder for area in sorted(areas, key=Area.order) if not self._file(team, area.folder).is_dir()]
        if gone:
            self._unlist(transaction, team, gone)

    def _unlist(self, transaction: SaveTransaction, team: str, gone: list[PurePosixPath]) -> None:
        """Take area folders repair removed out of the indexes of the shared folders above them, committed by the
        server apart from this save.

        While a cut-off save's folder was left on disk, a save in another area that changed the shared folders could
        list it and commit that listing (#179). Like any save's, the shared folders' turn is taken after the areas'.
        """
        self._shared_folders_turn(transaction, team)
        above = sorted({f for folder in gone for f in folder.parents}, key=lambda f: len(f.parts), reverse=True)
        transaction.mark(team, {self._turns.shared(team): [str(folder / INDEX_NAME) for folder in above]})
        before: dict[PurePosixPath, str | None] = {}
        pending = {folder.parent for folder in gone}
        try:
            # Deepest first, as a save does: a parent is listed again only when a folder under it went away.
            for folder in above:
                if folder in pending and not self._write_index(team, folder, before) and folder.parts:
                    pending.add(folder.parent)
            if before:
                repository = self._repository()
                blobs: dict[str, pygit2.Oid | None] = {}
                for path in before:
                    file = self._file(team, path)
                    blobs[f"{team}/{path}"] = repository.create_blob(file.read_bytes()) if file.is_file() else None
                message = (
                    "Unlist folders a cut-off save left\n\nA save cut off before it ended left them, and they were "
                    "removed.\n"
                )
                _land(repository, blobs, message, pygit2.Signature(*SERVER), self._turns.moving_main(transaction))
        except Exception:
            # The indexes go back to what main holds; if that fails too, the marker has the next holder do it.
            for path, text in before.items():
                file = self._file(team, path)
                if text is None:
                    _settled(lambda: file.unlink(missing_ok=True))
                else:
                    write_whole(file, text)
            transaction.unmark()
            raise
        transaction.unmark()

    def _put_back(
        self,
        transaction: SaveTransaction,
        team: str,
        turns: list[int],
        paths: list[str],
        ours: Callable[[PurePosixPath], bool],
    ) -> None:
        """Put the paths a cut-off save's markers name back to what main holds, removing the folders left empty that
        `ours` says are this save's to remove, and index its memories again as main holds them. The markers are
        cleared in the same transaction as the index, committed apart from this save, so a failure of this save
        doesn't bring them back."""
        log.warning("A save to %s was cut off before it ended; putting back %s", team, ", ".join(sorted(paths)))
        repository = self._repository()
        main = _main(repository)
        tree = repository[main].peel(pygit2.Tree) if main is not None else None
        writes: dict[PurePosixPath, Memory] = {}
        deletes: set[PurePosixPath] = set()
        files: list[Path] = []
        for name in sorted(set(paths)):
            path = PurePosixPath(name)
            file = self._file(team, path)
            files.append(file)
            key = f"{team}/{path}"
            entry = tree[key] if tree is not None and key in tree else None
            if entry is not None and entry.type == pygit2.enums.ObjectType.BLOB:
                blob = repository[entry.id]
                assert isinstance(blob, pygit2.Blob)
                data = blob.data
                if not file.is_file() or file.read_bytes() != data:
                    write_whole(file, data.decode("utf-8"))
                if path.name != INDEX_NAME:
                    try:
                        writes[path] = Memory.from_text(data.decode("utf-8"))
                    except Refused:
                        log.warning("Putting back %s: main holds no memory there to index", path)
                        deletes.add(path)
            else:
                _settled(lambda: file.unlink(missing_ok=True))
                if path.name != INDEX_NAME:
                    deletes.add(path)
        self._prune(team, [PurePosixPath(name) for name in paths], ours)
        self._parsed.forget(files)
        with transaction.apart(turns), ExitStack() as listening:
            if writes or deletes:
                for listener in self._listeners:
                    listening.enter_context(listener.on_change(team, writes, deletes))

    def _prune(self, team: str, paths: list[PurePosixPath], ours: Callable[[PurePosixPath], bool]) -> None:
        """Remove the folders above paths left empty, deepest first, of those that are ours to remove."""
        folders = {folder for path in paths for folder in path.parents if folder.parts and ours(folder)}
        for folder in sorted(folders, key=lambda f: len(f.parts), reverse=True):
            directory = self._file(team, folder)
            if directory.is_dir() and not any(directory.iterdir()):
                _settled(directory.rmdir)

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
        # The save's transaction opens first, since it holds the turns; they are taken before any file is read.
        with self._transaction() as transaction, self._take_turns(transaction, team, declared):
            self._repair_areas(transaction, team, declared)
            change = Change(self, team, message, declared)
            try:
                yield change
                self._apply(change, committer, transaction)
            finally:
                # Whether the save landed or was undone, what it touched is read again.
                self._parsed.forget(self._file(team, path) for path in [*change.writes, *change.deletes])

    def _apply(self, change: Change, committer: Committer, transaction: SaveTransaction) -> None:
        team = change.team
        if any(path.name == INDEX_NAME for path in change.writes):
            raise Refused(f"{INDEX_NAME} is reserved for folder indexes.")
        memories = [*change.writes, *change.deletes]
        # Deepest first, so a folder's index is written after the folders inside it.
        folders = sorted({f for path in memories for f in path.parents}, key=lambda f: len(f.parts), reverse=True)
        if not folders:
            return
        shared = self._reshapes_shared_folders(change)
        if shared:
            # Held until the save has landed or been undone, so no other save lists these folders in between.
            self._shared_folders_turn(transaction, team)
        moving_main = self._turns.moving_main(transaction)
        # What each file this save changes held before it: its memories now, each index as the save changes it.
        # Only these are committed and, if the save fails, put back, so no other area's change is ever undone.
        before = {path: self._previous(team, path) for path in memories}
        created = [folder for folder in folders if not self._file(team, folder).is_dir()]
        repository = self._repository()
        landed: _Landed | None = None
        try:
            # Before any file is written, so a save cut off from here on is put back by its turns' next holder.
            transaction.mark(team, self._marks(change, folders, shared))
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
            with ExitStack() as listening:
                for listener in self._listeners:
                    listening.enter_context(listener.on_change(team, dict(change.writes), set(change.deletes)))
                # Moving main is the save's last git step: every failure before it leaves main untouched.
                landed = self._commit(repository, team, list(before), change.message, committer, moving_main)
                for action in change.alongside:
                    action()
            # The turns are released only once the database has taken the save.
            transaction.commit()
        except Exception as error:
            self._undo(repository, team, before, created, landed, moving_main, transaction)
            if isinstance(error, Refused):
                raise
            log.exception("A save to %s failed and was undone", team)
            raise Refused(
                f"The memory was not saved: {_reason(error)}. Everything is as it was before this save; "
                "try again once that is fixed."
            ) from error

    def _marks(self, change: Change, folders: list[PurePosixPath], shared: bool) -> dict[int, list[str]]:
        """The paths a save may touch, by the turn each is under: its memories and the indexes of every folder above
        them, those of the shared folders only when it holds their turn."""
        marks: dict[int, list[str]] = {}
        for path in [*change.writes, *change.deletes, *(folder / INDEX_NAME for folder in folders)]:
            area = area_of(path)
            if area in change.areas:
                assert area is not None
                turn = self._turns.area(change.team, area)
            elif shared:
                turn = self._turns.shared(change.team)
            else:
                continue  # a shared folder's index, which this save can't change
            marks.setdefault(turn, []).append(str(path))
        return marks

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
        return pygit2.Repository(ordinary(self._root))

    def _commit(
        self,
        repository: pygit2.Repository,
        team: str,
        touched: list[PurePosixPath],
        message: str,
        committer: Committer,
        moving_main: MovingMain,
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
        return _land(repository, blobs, _cleaned(message + trailer), _author(committer), moving_main)

    def _undo(
        self,
        repository: pygit2.Repository,
        team: str,
        before: dict[PurePosixPath, str | None],
        created: list[PurePosixPath],
        landed: _Landed | None,
        moving_main: MovingMain,
        transaction: SaveTransaction,
    ) -> None:
        """Put back what a failed save did: the files it touched as `before` holds them, the folders it created, and,
        once it moved main, a revert commit on main putting back what its commit changed. main is never reset. Then
        its markers are cleared; if clearing them fails, the next save in its areas puts its paths back again.

        Every step is tried even when one before it fails, and a failed step is logged: a failure that stopped the
        save partway also stopped it from doing what the step would undo.
        """

        def attempt(what: str, step: Callable[[], object]) -> None:
            try:
                step()
            except Exception:
                log.exception("Undoing a failed save to %s: could not %s", team, what)

        if landed is not None:
            paths = [f"{team}/{path}" for path in before]
            attempt("revert its commit", lambda: _revert(repository, paths, landed, moving_main))
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
        attempt("clear its markers", transaction.unmark)

    def subscribe(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def teams(self) -> list[str]:
        return sorted(d.name for d in self._root.iterdir() if d.is_dir() and not d.name.startswith("."))
