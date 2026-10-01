"""Locks: a session's claim on a file in a repository that its coding agent is editing.

A lock is on one file: a project, a repository and the file's path from that repository's root, with forward slashes.
Its holder is the session that took it. It ends when its holder releases it, when the holder's session ends, or when
that session goes idle. Nothing sweeps: a lock whose holder is no longer active counts as gone wherever it is read, and
is cleared or moved when next touched. Who gets a file is decided by Postgres, in one row per file, so every worker
agrees (ADR-0013).

What other modules stand on, all of it on `Locks`:

- `take(session, path, repository)`: the lock, taken or kept, as a `Lock`; a `NeverLocks` for a file that never
  locks; or the refusal `Held`, whose `lock` says who holds the file.
- `release(session, path, repository)`: the holder gives the file up. Any other session is refused with `NotHeld`.
- `of(project_id, repository, path)`: the file's lock, with its holder, or None.
- `held(project_id)`: a project's locks, oldest first.
- `never_locks(project_id, path)`: the never-lock pattern a path matches, or None. The one place patterns are
  consulted.

`file_of(session, path, repository)` is the file a session means, refusing with `OutsideRepository` or `NoRepository`.
Only this module reads the `locks` table; a holder is a `Session`, which is the sessions module's.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import check_name
from shared_memory.sessions import Session, Sessions

SCHEMA = """
CREATE TABLE IF NOT EXISTS locks (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    repository TEXT NOT NULL,
    -- From the repository's root, with forward slashes.
    path TEXT NOT NULL,
    -- Its holder.
    session_id BIGINT NOT NULL REFERENCES sessions(id),
    taken_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, repository, path)
);

CREATE INDEX IF NOT EXISTS locks_by_session ON locks (session_id);
"""

# The files that never lock in any project: every session touches them, and none is edited by hand. Each is a glob.
# One without a slash is matched against the file's name, wherever the file is; one with a slash against the whole
# path from the repository's root. `*` and `?` stay within one folder; `**` crosses folders.
NEVER_LOCK: tuple[str, ...] = (
    # Lockfiles.
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
    # Generated files.
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.generated.*",
    "dist/**",
    "build/**",
)

# The longest path kept.
PATH_LIMIT = 500

# How often taking a lock looks again when the file changed hands between two looks.
_ATTEMPTS = 3

_DRIVE = re.compile(r"^[A-Za-z]:")
_COLUMNS = "project_id, repository, path, session_id, taken_at, last_used_at"

# What a module that knows sessions' activity gives: the activity of this session, or None when it has none.
ActivityOf = Callable[[Session], str | None]


def named(repository: str, path: str) -> str:
    """A file as it is written for a member: repository:path."""
    return f"{repository}:{path}"


@dataclass(frozen=True)
class Lock:
    """One file's lock and the session holding it."""

    project_id: str
    repository: str
    path: str
    holder: Session
    # The holder's activity, where its session has one.
    activity: str | None
    taken_at: datetime
    last_used_at: datetime


@dataclass(frozen=True)
class NeverLocks:
    """The answer for a file that never locks: no lock was taken, and none is needed to edit it."""

    repository: str
    path: str
    # The never-lock pattern the path matched.
    pattern: str

    @property
    def message(self) -> str:
        return (
            f"{named(self.repository, self.path)} never locks: it matches the never-lock pattern {self.pattern!r}. "
            "No lock was taken and none is needed; edit it."
        )


class Held(Refused):
    """Another active session holds the file. `lock` says who, and since when."""

    def __init__(self, lock: Lock, now: datetime) -> None:
        self.lock = lock
        holder = lock.holder
        activity = f"Their activity: {lock.activity}" if lock.activity else "Their session has stated no activity."
        super().__init__(
            f"{named(lock.repository, lock.path)} is locked by another session: {holder.member_name} "
            f"({holder.member_id}) in {holder.agent or 'a coding agent that has not said which it is'}, who last used "
            f"the lock {_ago(now, lock.last_used_at)} ({lock.last_used_at.isoformat()}). {activity} Don't edit the "
            "file: tell your member who holds it."
        )


class NotHeld(Refused):
    """The session asked to release a file it doesn't hold. `lock` is the file's lock when another session holds it."""

    def __init__(self, repository: str, path: str, lock: Lock | None) -> None:
        self.lock = lock
        file = named(repository, path)
        if lock is None:
            reason = f"This session holds no lock on {file}, and neither does any other, so there is nothing to release."
        else:
            reason = (
                f"This session holds no lock on {file}: {lock.holder.member_name} ({lock.holder.member_id})'s session "
                "does, and only a lock's holder releases it. Moving another session's lock is what a takeover is for."
            )
        super().__init__(reason)


class OutsideRepository(Refused):
    """A path that is not a file inside the repository."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"{path!r} is not a file inside the repository. Write a file's path from the repository's root, for "
            f"example src/webhooks/retry.py, in at most {PATH_LIMIT} characters; a file outside the repository never "
            "locks."
        )


class NoRepository(Refused):
    """Neither the call nor the session's connection names a repository."""

    def __init__(self) -> None:
        super().__init__(
            "This session's connection names no repository, so the file's repository isn't known. Call again and "
            "pass the repository's short name as `repository`."
        )


def from_root(path: str) -> str:
    """A path as a lock keeps it: from its repository's root, with forward slashes."""
    written = path.strip().replace("\\", "/")
    if not written or written.startswith("/") or _DRIVE.match(written) or len(written) > PATH_LIMIT:
        raise OutsideRepository(path)
    if any(ord(character) < 32 for character in written):
        raise OutsideRepository(path)
    kept = posixpath.normpath(written)
    if kept in (".", "..") or kept.startswith("../"):
        raise OutsideRepository(path)
    return kept


def file_of(session: Session, path: str, repository: str | None = None) -> tuple[str, str]:
    """The file a session means, as its repository and its path from the root. The repository is the one passed, or
    the session's own."""
    chosen = repository.strip() if repository and repository.strip() else session.repository
    if chosen is None:
        raise NoRepository()
    return check_name("Repository name", chosen), from_root(path)


def matching(patterns: Sequence[str], path: str) -> str | None:
    """The first of these never-lock patterns the path matches, or None."""
    name = posixpath.basename(path)
    for pattern in patterns:
        if _glob(pattern).match(path if "/" in pattern else name):
            return pattern
    return None


def _glob(pattern: str) -> re.Pattern[str]:
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    translated = {"**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.compile("".join(translated.get(part) or re.escape(part) for part in parts) + r"\Z")


def _ago(now: datetime, then: datetime) -> str:
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 1:
        return "less than a minute ago"
    return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"


class Locks:
    def __init__(self, db: Database, sessions: Sessions, clock: Clock, activity_of: ActivityOf | None = None) -> None:
        """activity_of supplies each holder's activity; without it no lock carries one."""
        self._db = db
        self._sessions = sessions
        self._clock = clock
        self._activity_of: ActivityOf = activity_of or (lambda session: None)
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)
        sessions.on_gone(self._end)

    def _end(self, conn: Conn, session_ids: Sequence[int]) -> None:
        """A session that ended or is back from idle holds nothing."""
        conn.execute("DELETE FROM locks WHERE session_id = ANY(%s)", (list(session_ids),))

    def never_locks(self, project_id: str, path: str) -> str | None:
        """The never-lock pattern this path, written from its repository's root, matches in this project, or None
        when the file locks. Every question of whether a file locks is asked here."""
        return matching(NEVER_LOCK, path)

    def take(self, session: Session, path: str, repository: str | None = None) -> Lock | NeverLocks:
        """Take the lock on a file for this session, or keep the one it holds, moving when it was last used. A file
        that never locks is answered so, and no lock is taken. Refused with `Held` when another active session holds
        it."""
        repository, path = file_of(session, path, repository)
        pattern = self.never_locks(session.project_id, path)
        if pattern is not None:
            return NeverLocks(repository, path, pattern)
        file = (session.project_id, repository, path)
        now = self._clock()
        for _ in range(_ATTEMPTS):
            mine, kept = self._take(file, session, now)
            if mine is not None:
                return self._lock(mine, session)
            # The holder was active when the row was read. One that ended since has left the file free: look again.
            holder = self._active(session.project_id).get(kept["session_id"]) if kept else None
            if holder is not None:
                assert kept is not None
                raise Held(self._lock(kept, holder), now)
        raise Refused(f"{named(repository, path)} kept changing hands, so its lock wasn't taken. Call take_lock again.")

    def _take(self, file: tuple[str, str, str], session: Session, now: datetime) -> tuple[Any, Any]:
        """One try: the lock's row if the session now holds it, or else the row of the active holder's lock. Neither
        means the file changed hands between the write and the read."""
        with self._db.transaction() as conn:
            # Two sessions taking a free file both insert; Postgres lets one row in, and the other waits for it and
            # then finds a holder that isn't itself.
            mine = conn.execute(
                "INSERT INTO locks (project_id, repository, path, session_id, taken_at, last_used_at)"
                " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (project_id, repository, path)"
                " DO UPDATE SET last_used_at = EXCLUDED.last_used_at WHERE locks.session_id = EXCLUDED.session_id"
                f" RETURNING {_COLUMNS}",
                (*file, session.id, now, now),
            ).fetchone()
            if mine is not None:
                return mine, None
            kept = conn.execute(
                "SELECT project_id, repository, path, session_id, taken_at, last_used_at FROM locks"
                " WHERE project_id = %s AND repository = %s AND path = %s FOR UPDATE",
                file,
            ).fetchone()
            if kept is None:
                return None, None
            if self._sessions.still_active([kept["session_id"]], conn):
                return None, kept
            # Its holder ended or went idle without the lock being cleared: the row is held here, so it moves.
            moved = conn.execute(
                "UPDATE locks SET session_id = %s, taken_at = %s, last_used_at = %s"
                f" WHERE project_id = %s AND repository = %s AND path = %s RETURNING {_COLUMNS}",
                (session.id, now, now, *file),
            ).fetchone()
            return moved, None

    def release(self, session: Session, path: str, repository: str | None = None) -> Lock:
        """Release a file this session holds, and give back the lock that ended. Refused with `NotHeld` for a session
        that doesn't hold it."""
        repository, path = file_of(session, path, repository)
        with self._db.transaction() as conn:
            ended = conn.execute(
                "DELETE FROM locks WHERE project_id = %s AND repository = %s AND path = %s AND session_id = %s"
                " RETURNING project_id, repository, path, session_id, taken_at, last_used_at",
                (session.project_id, repository, path, session.id),
            ).fetchone()
        if ended is None:
            raise NotHeld(repository, path, self.of(session.project_id, repository, path))
        return self._lock(ended, session)

    def of(self, project_id: str, repository: str, path: str) -> Lock | None:
        """The lock on this file, or None when no active session holds one. Whether the asker may reach the project
        is the asker's to check."""
        with self._db.transaction() as conn:
            kept = conn.execute(
                "SELECT project_id, repository, path, session_id, taken_at, last_used_at FROM locks"
                " WHERE project_id = %s AND repository = %s AND path = %s",
                (project_id, repository, path),
            ).fetchone()
        holder = self._active(project_id).get(kept["session_id"]) if kept else None
        return self._lock(kept, holder) if holder is not None else None

    def held(self, project_id: str) -> list[Lock]:
        """A project's locks, oldest first: those whose holder is active. Whether the asker may reach the project is
        the asker's to check."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT project_id, repository, path, session_id, taken_at, last_used_at FROM locks"
                " WHERE project_id = %s ORDER BY taken_at, repository, path",
                (project_id,),
            ).fetchall()
        active = self._active(project_id) if rows else {}
        return [self._lock(row, active[row["session_id"]]) for row in rows if row["session_id"] in active]

    def _active(self, project_id: str) -> dict[int, Session]:
        return {session.id: session for session in self._sessions.active(project_id)}

    def _lock(self, row: Any, holder: Session) -> Lock:
        return Lock(
            project_id=row["project_id"],
            repository=row["repository"],
            path=row["path"],
            holder=holder,
            activity=self._activity_of(holder),
            taken_at=row["taken_at"].astimezone(UTC),
            last_used_at=row["last_used_at"].astimezone(UTC),
        )
