"""Locks: a session's claim on a file in a repository that its coding agent is editing.

A lock is on one file: a project, a repository and the file's path from that repository's root, with forward slashes.
Its holder is the session that took it. It ends when its holder releases it, when the holder's session ends, or when
that session goes idle; a takeover moves it to another session, and the old holder is told once. Nothing sweeps: a lock whose holder is no longer active counts as gone wherever it is read, and
is cleared or moved when next touched. Who gets a file is decided by Postgres, in one row per file, so every worker
agrees (ADR-0013).

What other modules stand on, all of it on `Locks`:

- `take(session, path, repository)`: the lock, taken or kept, as a `Lock`; a `NeverLocks` for a file that never
  locks; or the refusal `Held`, whose `lock` says who holds the file. With `takeover=True` another active session's
  lock moves to this session instead of refusing it.
- `waiting_notices(session)`: what a session is told once of each takeover of a lock it held.
- `release(session, path, repository)`: the holder gives the file up. Any other session is refused with `NotHeld`.
- `of(project_id, repository, path)`: the file's lock, with its holder, or None.
- `held(project_id)`: a project's locks, oldest first.
- `never_locks(project_id, path)`: the never-lock pattern a path matches, or None. The one place patterns are
  consulted.

`file_of(session, path, repository)` is the file a session means, refusing with `OutsideRepository` or `NoRepository`.
Only this module reads the `locks` table; a holder is a `Session`, which is the sessions module's.

A project's own never-lock patterns are `ProjectPatterns`, beside the built-in `NEVER_LOCK`:

- `of(project_id)`: the project's patterns, oldest first, each a `NeverLockPattern`.
- `add(caller, pattern)` and `remove(caller, pattern)`: for the project's leads and the team's admins. Each writes an
  audit log entry. A lock held on a file the added pattern matches ends there.

Only this module reads the `never_lock_patterns` table, and `Locks.never_locks` is still the one place a path is
matched against them.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared_memory.audit import NEVER_LOCK_PATTERN_ADDED, NEVER_LOCK_PATTERN_REMOVED, Audit
from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, check_name
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

-- A project's own never-lock patterns, beside the built-in list. One list for all of the project's repositories.
CREATE TABLE IF NOT EXISTS never_lock_patterns (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    pattern TEXT NOT NULL,
    -- The member ID of whoever added it.
    added_by TEXT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, pattern)
);

-- A takeover its old holder has not been told of yet.
CREATE TABLE IF NOT EXISTS takeovers (
    id BIGSERIAL PRIMARY KEY,
    -- The old holder.
    session_id BIGINT NOT NULL REFERENCES sessions(id),
    repository TEXT NOT NULL,
    path TEXT NOT NULL,
    -- Who took the file over, as the old holder is told it: the notice says what was so at the takeover.
    by_name TEXT NOT NULL,
    by_member_id TEXT NOT NULL,
    by_agent TEXT,
    by_activity TEXT,
    taken_over_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS takeovers_by_session ON takeovers (session_id);
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

# The longest never-lock pattern a project keeps.
PATTERN_LIMIT = 200

# What a glob in another dialect uses and these patterns don't read.
_UNREAD = "[]{}"

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
            "file: tell your member who holds it. Your member can ask for a takeover, which moves the lock to this "
            "session at once and tells the holder on its next prompt. That is your member's decision, never yours: "
            "only once they have said so, call take_lock again with `takeover` true."
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


@dataclass(frozen=True)
class NeverLockPattern:
    """One of a project's own never-lock patterns."""

    pattern: str
    # The member ID of whoever added it.
    added_by: str
    added_at: datetime


class UnusablePattern(Refused):
    """What was written is not a glob these patterns can be matched with."""

    def __init__(self, pattern: str, reason: str) -> None:
        super().__init__(
            f"{pattern!r} isn't a usable never-lock pattern: {reason}. A pattern is a glob of at most {PATTERN_LIMIT} "
            "characters, in which `*`, `?` and `**` are read: `*` and `?` stay within one folder and `**` crosses "
            "folders. One without a slash matches a file's name in any folder, for example *.snap; one with a slash "
            "matches the whole path from the repository's root, for example src/generated/**."
        )


def usable(pattern: str) -> str:
    """A never-lock pattern as a project keeps it, with forward slashes. Refused with `UnusablePattern` when it
    could not match a file inside a repository, would match every file, or is written in a glob dialect that isn't
    read here."""
    written = pattern.strip().replace("\\", "/")
    if not written:
        raise UnusablePattern(pattern, "it is empty")
    if len(written) > PATTERN_LIMIT:
        raise UnusablePattern(pattern, f"it is longer than {PATTERN_LIMIT} characters")
    if any(ord(character) < 32 for character in written):
        raise UnusablePattern(pattern, "it has a control character in it")
    if written.startswith("/") or _DRIVE.match(written):
        raise UnusablePattern(pattern, "a path is matched from the repository's root, so it starts with no slash")
    if written.endswith("/"):
        raise UnusablePattern(pattern, f"it names a folder, and files are what lock; write {written}** for its files")
    if any(part in (".", "..", "") for part in written.split("/")):
        raise UnusablePattern(pattern, "it has an empty, `.` or `..` part, which no path kept for a lock has")
    if written.startswith("!") or any(character in _UNREAD for character in written):
        raise UnusablePattern(pattern, "`!`, `[...]` and `{...}` are not read")
    if not any(character.isalnum() for character in written):
        raise UnusablePattern(pattern, "it would match every file, and then nothing in the project would lock")
    return written


def _glob(pattern: str) -> re.Pattern[str]:
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    translated = {"**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.compile("".join(translated.get(part) or re.escape(part) for part in parts) + r"\Z")


def _ago(now: datetime, then: datetime) -> str:
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 1:
        return "less than a minute ago"
    return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"


def _taken_over(row: Any) -> str:
    """What an old holder is told of one takeover."""
    by = f"{row['by_name']} ({row['by_member_id']})" + (f" in {row['by_agent']}" if row["by_agent"] else "")
    activity = f"Their activity: {row['by_activity']}" if row["by_activity"] else "Their session has stated no activity."
    return (
        f"[session] This session no longer holds the lock on {named(row['repository'], row['path'])}: {by} moved it "
        f"to their own session with a takeover. {activity} Stop editing the file and tell your member; taking its "
        "lock again will be refused while their session holds it."
    )


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
        conn.execute("DELETE FROM takeovers WHERE session_id = ANY(%s)", (list(session_ids),))

    def never_locks(self, project_id: str, path: str) -> str | None:
        """The never-lock pattern this path, written from its repository's root, matches in this project, or None
        when the file locks: one of the built-in list, or else one of the project's own. Every question of whether a
        file locks is asked here."""
        built_in = matching(NEVER_LOCK, path)
        if built_in is not None:
            return built_in
        with self._db.transaction() as conn:
            return matching(_patterns_of(conn, project_id), path)

    def take(
        self, session: Session, path: str, repository: str | None = None, takeover: bool = False
    ) -> Lock | NeverLocks:
        """Take the lock on a file for this session, or keep the one it holds, moving when it was last used. A file
        that never locks is answered so, and no lock is taken. Refused with `Held` when another active session holds
        it, unless this is a takeover: then the lock moves to this session, and the old holder is told with
        `waiting_notices`. A takeover of a file no other active session holds is an ordinary take."""
        repository, path = file_of(session, path, repository)
        pattern = self.never_locks(session.project_id, path)
        if pattern is not None:
            return NeverLocks(repository, path, pattern)
        file = (session.project_id, repository, path)
        now = self._clock()
        for _ in range(_ATTEMPTS):
            mine, kept = self._take(file, session, now, takeover)
            if mine is not None:
                return self._lock(mine, session)
            # The holder was active when the row was read. One that ended since has left the file free: look again.
            holder = self._active(session.project_id).get(kept["session_id"]) if kept else None
            if holder is not None:
                assert kept is not None
                raise Held(self._lock(kept, holder), now)
        raise Refused(f"{named(repository, path)} kept changing hands, so its lock wasn't taken. Call take_lock again.")

    def _take(self, file: tuple[str, str, str], session: Session, now: datetime, takeover: bool) -> tuple[Any, Any]:
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
            held = bool(self._sessions.still_active([kept["session_id"]], conn))
            if held and not takeover:
                return None, kept
            # A takeover, or a holder that ended or went idle without the lock being cleared. The row is held here,
            # so it moves: a release or another takeover racing this one waits, and then finds this session its
            # holder. Only an active holder had a lock to lose, so only it is told.
            if held:
                self._tell(conn, kept, session, now)
            moved = conn.execute(
                "UPDATE locks SET session_id = %s, taken_at = %s, last_used_at = %s"
                f" WHERE project_id = %s AND repository = %s AND path = %s RETURNING {_COLUMNS}",
                (session.id, now, now, *file),
            ).fetchone()
            return moved, None

    def _tell(self, conn: Conn, kept: Any, by: Session, now: datetime) -> None:
        """Keep, for the holder of this lock's row, the word that `by` took the file over."""
        conn.execute(
            "INSERT INTO takeovers"
            " (session_id, repository, path, by_name, by_member_id, by_agent, by_activity, taken_over_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                kept["session_id"],
                kept["repository"],
                kept["path"],
                by.member_name,
                by.member_id,
                by.agent,
                self._activity_of(by),
                now,
            ),
        )

    def waiting_notices(self, session: Session) -> list[str]:
        """What this session is told once, with its next prompt or the result of its next tool call: each takeover
        of a lock it held, oldest first. Asking marks them told."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "DELETE FROM takeovers WHERE session_id = %s"
                " RETURNING id, repository, path, by_name, by_member_id, by_agent, by_activity",
                (session.id,),
            ).fetchall()
        return [_taken_over(row) for row in sorted(rows, key=lambda row: row["id"])]

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


def _patterns_of(conn: Conn, project_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT pattern FROM never_lock_patterns WHERE project_id = %s ORDER BY added_at, pattern", (project_id,)
    ).fetchall()
    return [row["pattern"] for row in rows]


class ProjectPatterns:
    """A project's own never-lock patterns: one list for all of its repositories, beside the built-in list, which
    always applies. Its table is set up with `Locks`'s, so build `Locks` first."""

    def __init__(self, db: Database, identity: Identity, audit: Audit, clock: Clock) -> None:
        self._db = db
        self._identity = identity
        self._audit = audit
        self._clock = clock

    def of(self, project_id: str) -> list[NeverLockPattern]:
        """The project's own patterns, oldest first. Whether the asker may reach the project is the asker's to
        check."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT pattern, added_by, added_at FROM never_lock_patterns WHERE project_id = %s"
                " ORDER BY added_at, pattern",
                (project_id,),
            ).fetchall()
        return [NeverLockPattern(row["pattern"], row["added_by"], row["added_at"].astimezone(UTC)) for row in rows]

    def add(self, caller: Caller, pattern: str) -> NeverLockPattern:
        """Add a pattern to the caller's project. A lock held on a file it matches ends: the file never locks from
        here on, so the lock would block nobody and only be listed."""
        project_id = self._changeable_by(caller)
        written = usable(pattern)
        if written in NEVER_LOCK:
            raise Refused(f"{written!r} is built in: it already never locks in every project.")
        added = NeverLockPattern(written, caller.member_id, self._clock())
        with self._db.transaction() as conn:
            kept = conn.execute(
                "INSERT INTO never_lock_patterns (project_id, pattern, added_by, added_at) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (project_id, pattern) DO NOTHING RETURNING pattern",
                (project_id, written, added.added_by, added.added_at),
            ).fetchone()
            if kept is None:
                raise Refused(f"{written!r} is already one of this project's never-lock patterns.")
            held = conn.execute("SELECT repository, path FROM locks WHERE project_id = %s", (project_id,)).fetchall()
            for lock in held:
                if matching([written], lock["path"]) is not None:
                    conn.execute(
                        "DELETE FROM locks WHERE project_id = %s AND repository = %s AND path = %s",
                        (project_id, lock["repository"], lock["path"]),
                    )
        self._record(caller, NEVER_LOCK_PATTERN_ADDED, project_id, written)
        return added

    def remove(self, caller: Caller, pattern: str) -> str:
        """Remove one of the caller's project's own patterns, and give it back as it was kept. Files it matched lock
        again."""
        project_id = self._changeable_by(caller)
        written = pattern.strip().replace("\\", "/")
        if written in NEVER_LOCK:
            raise Refused(f"{written!r} is built in: it applies to every project and can't be removed.")
        with self._db.transaction() as conn:
            removed = conn.execute(
                "DELETE FROM never_lock_patterns WHERE project_id = %s AND pattern = %s RETURNING pattern",
                (project_id, written),
            ).fetchone()
        if removed is None:
            raise Refused(
                f"{written!r} isn't one of this project's never-lock patterns. Call never_lock with nothing to read "
                "them."
            )
        self._record(caller, NEVER_LOCK_PATTERN_REMOVED, project_id, written)
        return written

    def _changeable_by(self, caller: Caller) -> str:
        """The caller's project, when they may change its patterns."""
        project_id = caller.require_project().project_id
        member = caller.member
        if not (member.is_owner or member.is_admin or project_id in self._identity.leads_of(member)):
            raise Refused(
                "Only this project's leads and the team's admins can add or remove its never-lock patterns. Any "
                "member of the project can read them, by calling never_lock with nothing."
            )
        return project_id

    def _record(self, caller: Caller, change: str, project_id: str, pattern: str) -> None:
        detail = {"agent": caller.agent} if caller.agent is not None else {}
        self._audit.record(change, member=caller.member, project_id=project_id, target=pattern, detail=detail)
