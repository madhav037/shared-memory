"""The tied-file index: which memories are tied to which files (CONTEXT.md, Tied file; spec #503).

A memory's tied files are written in its header as repository:path. A path with no glob characters is that one file
from the repository's root: `billing-api:package.json` ties the root's package.json alone. One with glob characters is
read with the never-lock patterns' glob rules (`locks.usable` and `locks.matching`): `*` and `?` stay within one
folder, `**` crosses folders, and a glob without a slash matches a file's name in any folder. The index holds one row per active memory and tie, with no readable
content, and like the search index it is kept in step with every save and rebuilt from the files on disk (ADR-0002).

What other modules stand on, all of it on `TiedFiles`:

- `tied_to(team, repository, paths, reach)`: the active memories within a `Reach` tied to any of a repository's files,
  as `Tie`s, one per memory. The one place a file is matched against tied files.
- `on_change(team, writes, deletes)`: the store's listener, so a save, edit, promote, supersede, retire or delete
  moves the ties with it.
- `rebuild(store)` for `reindex`, and `catch_up(store)` to fill the index the first time a server has it.

`tie_of(entry)` reads one tied file as written into a `TiedFile`, refusing what can't be one; `file_named(file)` reads
a file written repository:path, as a session asks about one, into a `RepositoryFile`. Only this module reads the `tied_files` table.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath

from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import NAME_PATTERN, check_name
from shared_memory.index import Reach
from shared_memory.locks import GLOB_CHARACTERS, UnusablePattern, from_root, matching, named, usable
from shared_memory.memory import Memory, locate
from shared_memory.store import MemoryStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS tied_files (
    team TEXT NOT NULL,
    -- The memory's path in the team's folder.
    path TEXT NOT NULL,
    repository TEXT NOT NULL,
    -- From the repository's root, with forward slashes; a file or a glob.
    glob TEXT NOT NULL,
    -- Where the memory sits, decoded from its path, so a lookup keeps to a reach.
    level TEXT NOT NULL,
    project_id TEXT,
    member_id TEXT,
    PRIMARY KEY (team, path, repository, glob)
);

CREATE INDEX IF NOT EXISTS tied_files_by_repository ON tied_files (team, repository);
"""


@dataclass(frozen=True, order=True)
class TiedFile:
    """One tied file: its repository, and its path or glob from the repository's root."""

    repository: str
    glob: str

    @property
    def written(self) -> str:
        """As it is written: repository:path."""
        return named(self.repository, self.glob)


def ties(glob: str, path: str) -> bool:
    """Whether a tied file's path or glob ties a file, by its path from the repository's root: a path with no glob
    characters is that one file; a glob follows the never-lock pattern rules."""
    if not any(character in GLOB_CHARACTERS for character in glob):
        return glob == path
    return matching([glob], path) is not None


@dataclass(frozen=True)
class RepositoryFile:
    """A file in one of a project's repositories, by its path from the repository's root."""

    repository: str
    path: str

    @property
    def written(self) -> str:
        """As it is written for a member: repository:path."""
        return named(self.repository, self.path)


@dataclass(frozen=True)
class Tie:
    """A memory tied to a file, and the tied file that ties it."""

    # The memory's path in the team's folder.
    memory_path: str
    repository: str
    glob: str

    @property
    def tied_file(self) -> str:
        """The tied file as it is written: repository:glob."""
        return named(self.repository, self.glob)


def tie_of(entry: str) -> TiedFile:
    """One tied file as its repository and its path or glob from the repository's root. Refused when it isn't written as
    repository:path, or its path isn't a glob the never-lock pattern rules can read, with their reason."""
    repository, _, path = entry.partition(":")
    if not NAME_PATTERN.match(repository) or not path.strip() or "\n" in entry:
        raise Refused(f"Tied file {entry!r} must be written as repository:path, for example billing-api:package.json.")
    try:
        return TiedFile(repository, usable(path))
    except UnusablePattern as unusable:
        raise Refused(
            f"Tied file {entry!r} isn't a usable glob: {unusable.reason}. A tied file is a file or a folder glob "
            "from the repository's root, for example billing-api:src/tax/**: `*` and `?` stay within one folder "
            "and `**` crosses folders."
        ) from unusable


def file_named(file: str) -> RepositoryFile:
    """A file as a member writes it, repository:path, as its repository and its path from the repository's root."""
    repository, _, path = file.strip().partition(":")
    try:
        return RepositoryFile(check_name("Repository name", repository), from_root(path))
    except Refused as refused:
        raise Refused(
            f"{file!r} isn't a file written as repository:path, with the path from the repository's root, for example "
            "billing-api:src/tax/rates.py."
        ) from refused


def _tied_files_of(memory: Memory) -> set[TiedFile]:
    """The tied files an active memory ties itself to. One saved before globs were checked, which can't be read as
    one, ties nothing rather than stopping the save that carries it."""
    if memory.status != "active":
        return set()
    tied = set()
    for entry in memory.tied_files:
        try:
            tied.add(tie_of(str(entry)))
        except Refused:
            continue
    return tied


class TiedFiles:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._new = False
        if db.sets_up:
            with db.transaction() as conn:
                self._new = (
                    conn.execute(
                        "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema()"
                        " AND table_name = 'tied_files'"
                    ).fetchone()
                    is None
                )
                conn.execute(SCHEMA)

    def catch_up(self, store: MemoryStore) -> None:
        """Fill the index from the files on disk if this server has only just made it."""
        if self._new:
            self.rebuild(store)
            self._new = False

    @staticmethod
    def _update(conn: Conn, team: str, path: PurePosixPath, memory: Memory) -> None:
        conn.execute("DELETE FROM tied_files WHERE team = %s AND path = %s", (team, str(path)))
        tied = _tied_files_of(memory)
        if not tied:
            return
        location = locate(str(path))
        conn.cursor().executemany(
            "INSERT INTO tied_files (team, path, repository, glob, level, project_id, member_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (team, str(path), each.repository, each.glob, location.level, location.project_id, location.member_id)
                for each in sorted(tied)
            ],
        )

    @contextmanager
    def on_change(
        self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> Iterator[None]:
        """Move the ties with a save, in one transaction committed once the save has landed."""
        with self._db.transaction() as conn:
            gone = [str(path) for path in deletes]
            if gone:
                conn.execute("DELETE FROM tied_files WHERE team = %s AND path = ANY(%s)", (team, gone))
            for path, memory in writes.items():
                self._update(conn, team, path, memory)
            yield

    def rebuild(self, store: MemoryStore) -> int:
        """Build the index again from the memory files on disk, giving how many memories were read."""
        count = 0
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM tied_files")
            for team in store.teams():
                for _, memories in store.walk(team, PurePosixPath()):
                    for path, memory in memories:
                        self._update(conn, team, path, memory)
                        count += 1
        return count

    def tied_to(self, team: str, repository: str, paths: Iterable[str], reach: Reach) -> list[Tie]:
        """The active memories within reach tied to any of a repository's files, each by its path from the
        repository's root, in one lookup and in path order: one `Tie` for each memory, naming the first of its tied
        files that ties one of them."""
        files = list(dict.fromkeys(paths))
        if not files:
            return []
        within, params = reach.where()
        with self._db.transaction() as conn:
            rows = conn.execute(
                f"SELECT path, glob FROM tied_files WHERE team = %(team)s AND repository = %(repository)s AND {within}"  # noqa: S608  # values are bound as parameters; only the reach's clause is spliced in
                " ORDER BY path, glob",
                {**params, "team": team, "repository": repository},
            ).fetchall()
        globs: dict[str, list[str]] = {}
        for row in rows:
            globs.setdefault(str(row["path"]), []).append(str(row["glob"]))
        found = []
        for memory, patterns in globs.items():
            glob = next((each for each in patterns if any(ties(each, path) for path in files)), None)
            if glob is not None:
                found.append(Tie(memory, repository, glob))
        return found
