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
- `take_all(session, paths)`: the locks on every file of one edit, or none: refused with `Held`, it gives back what
  it took.
- `before_edit(session, paths)`: the before-edit hook's decision: `take_all`, and the reason an edit is blocked
  (`Held`'s, ending with `TAKEOVER_IS_POSSIBLE`) or None to let it through.
- `waiting_notices(session)`: what a session is told once of each takeover of a lock it held, and of each lock of
  its own that an added never-lock pattern ended.
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
from operator import itemgetter
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

-- A lock that ended because a never-lock pattern added to its project matches its file, which its holder has not been
-- told yet.
CREATE TABLE IF NOT EXISTS locks_ended_by_pattern (
    id BIGSERIAL PRIMARY KEY,
    -- The holder the lock ended for.
    session_id BIGINT NOT NULL REFERENCES sessions(id),
    repository TEXT NOT NULL,
    path TEXT NOT NULL,
    pattern TEXT NOT NULL,
    -- Who added the pattern, as the holder is told it.
    by_name TEXT NOT NULL,
    by_member_id TEXT NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS locks_ended_by_pattern_by_session ON locks_ended_by_pattern (session_id);
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
    # Whether the call that gave this lock is the one that made its session the holder, rather than finding it so.
    taken_now: bool = False


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
        self._held = (
            f"{named(lock.repository, lock.path)} is locked by another session: {holder.member_name} "
            f"({holder.member_id}) in {holder.agent or 'a coding agent that has not said which it is'}, who last used "
            f"the lock {_ago(now, lock.last_used_at)} ({lock.last_used_at.isoformat()}). {activity} Don't edit the "
            "file: tell your member who holds it."
        )
        super().__init__(self.told(TAKE_LOCK_AGAIN))

    def told(self, takeover: str) -> str:
        """Who holds the file, followed by how a takeover is asked for where the session is told it: the one place
        the takeover advice goes, so it is stated once."""
        return f"{self._held} {takeover}"


# How a session refused by take_lock is told a takeover is possible.
TAKE_LOCK_AGAIN = (
    "Your member can ask for a takeover, which moves the lock to this session at once and tells the holder on its "
    "next prompt. That is your member's decision, never yours: only once they have said so, call take_lock again with "
    "`takeover` true."
)

# How a session whose edit the before-edit hook blocked is told a takeover is possible: after who holds the file, the
# way on, which is the member's to choose.
TAKEOVER_IS_POSSIBLE = (
    "A takeover is possible: it moves the lock to this session at once, and the holder is told on their next prompt. "
    "Ask your member first, and only once they say so call take_lock with this file's path from the repository's "
    "root, this session and takeover: true, then edit the file."
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


def slashed(path: str) -> str:
    """A path or pattern as written, trimmed and with forward slashes: the one way each is read before anything else."""
    return path.strip().replace("\\", "/")


def on_a_drive(path: str) -> bool:
    """Whether a path starts with a Windows drive."""
    return _DRIVE.match(path) is not None


def absolute(path: str) -> bool:
    """Whether a slashed path starts at a file system's root or a Windows drive, rather than inside a folder."""
    return path.startswith("/") or on_a_drive(path)


def from_root(path: str) -> str:
    """A path as a lock keeps it: from its repository's root, with forward slashes."""
    written = slashed(path)
    if not written or absolute(written) or len(written) > PATH_LIMIT:
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
    written = slashed(pattern)
    if not written:
        raise UnusablePattern(pattern, "it is empty")
    if len(written) > PATTERN_LIMIT:
        raise UnusablePattern(pattern, f"it is longer than {PATTERN_LIMIT} characters")
    if any(ord(character) < 32 for character in written):
        raise UnusablePattern(pattern, "it has a control character in it")
    if absolute(written):
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


def _ended_by_pattern(row: Any) -> str:
    """What a holder is told of one lock that ended because its file now matches a never-lock pattern."""
    return (
        f"[session] This session no longer holds the lock on {named(row['repository'], row['path'])}: "
        f"{row['by_name']} ({row['by_member_id']}) added the never-lock pattern {row['pattern']!r} to this project, "
        "which the file matches, so the file never locks from here on and its lock ended. No lock is needed to edit "
        "it, and none stops another session editing it at the same time: tell your member."
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
        conn.execute("DELETE FROM locks_ended_by_pattern WHERE session_id = ANY(%s)", (list(session_ids),))

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
        # Asked before the lock's row is held, so nothing else is read while a racing session waits for it.
        activity = self._activity_of(session) if takeover else None
        for _ in range(_ATTEMPTS):
            mine, kept = self._take(file, session, now, takeover, activity)
            if mine is not None:
                return self._lock(mine, session)
            # The holder was active when the row was read. One that ended since has left the file free: look again.
            holder = self._active(session.project_id).get(kept["session_id"]) if kept else None
            if holder is not None:
                assert kept is not None
                raise Held(self._lock(kept, holder), now)
        raise Refused(f"{named(repository, path)} kept changing hands, so its lock wasn't taken. Call take_lock again.")

    def take_all(self, session: Session, paths: Sequence[str]) -> None:
        """Take the lock on each of these files for one edit that changes them all, or on none of them. Refused with
        `Held` for the first one another active session holds, and the locks this call took before reaching it are
        released again: the edit is not happening, so they would block others for nothing. A lock the session held
        before the call stays its. A file that never locks, or is outside the repository, is passed over."""
        taken: list[Lock] = []
        for path in paths:
            try:
                lock = self.take(session, path)
            except (OutsideRepository, NoRepository):
                continue
            except Held:
                for each in taken:
                    self._give_back(session, each)
                raise
            if isinstance(lock, Lock) and lock.taken_now:
                taken.append(lock)

    def before_edit(self, session: Session, paths: Sequence[str]) -> str | None:
        """The before-edit hook's decision on an edit of these files: why it is blocked, which is only ever that
        another active session holds one of them, or None to let it through, with each file's lock taken or kept for
        this session where the file locks. A file that never locks, or is outside the repository, lets it through."""
        try:
            self.take_all(session, paths)
        except Held as refused:
            return refused.told(TAKEOVER_IS_POSSIBLE)
        return None

    def _give_back(self, session: Session, lock: Lock) -> None:
        """Release a lock this session took a moment ago, unless a takeover has moved it since."""
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM locks WHERE project_id = %s AND repository = %s AND path = %s AND session_id = %s",
                (lock.project_id, lock.repository, lock.path, session.id),
            )

    def _take(
        self, file: tuple[str, str, str], session: Session, now: datetime, takeover: bool, activity: str | None
    ) -> tuple[Any, Any]:
        """One try: the lock's row if the session now holds it, or else the row of the active holder's lock. Neither
        means the file changed hands between the write and the read."""
        with self._db.transaction() as conn:
            # Two sessions taking a free file both insert; Postgres lets one row in, and the other waits for it and
            # then finds a holder that isn't itself.
            mine = conn.execute(
                "INSERT INTO locks (project_id, repository, path, session_id, taken_at, last_used_at)"  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
                " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (project_id, repository, path)"
                " DO UPDATE SET last_used_at = EXCLUDED.last_used_at WHERE locks.session_id = EXCLUDED.session_id"
                # A row just inserted has no xmax; one that was there, and only had its last use moved, has.
                f" RETURNING {_COLUMNS}, (xmax = 0) AS taken_now",
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
                self._tell(conn, kept, session, activity, now)
            moved = conn.execute(
                "UPDATE locks SET session_id = %s, taken_at = %s, last_used_at = %s"  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
                f" WHERE project_id = %s AND repository = %s AND path = %s RETURNING {_COLUMNS}, TRUE AS taken_now",
                (session.id, now, now, *file),
            ).fetchone()
            return moved, None

    def _tell(self, conn: Conn, kept: Any, by: Session, activity: str | None, now: datetime) -> None:
        """Keep, for the holder of this lock's row, the word that `by` took the file over, and for what activity."""
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
                activity,
                now,
            ),
        )

    def waiting_notices(self, session: Session) -> list[str]:
        """What this session is told once, with its next prompt or the result of its next tool call: each takeover
        of a lock it held, then each lock of its own that an added never-lock pattern ended, oldest first. Asking
        marks them told."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "DELETE FROM takeovers WHERE session_id = %s"
                " RETURNING id, repository, path, by_name, by_member_id, by_agent, by_activity",
                (session.id,),
            ).fetchall()
            ended = conn.execute(
                "DELETE FROM locks_ended_by_pattern WHERE session_id = %s"
                " RETURNING id, repository, path, pattern, by_name, by_member_id",
                (session.id,),
            ).fetchall()
        return [
            *(_taken_over(row) for row in sorted(rows, key=itemgetter("id"))),
            *(_ended_by_pattern(row) for row in sorted(ended, key=itemgetter("id"))),
        ]

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
            taken_now=bool(row.get("taken_now", False)),
        )


def _patterns_of(conn: Conn, project_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT pattern FROM never_lock_patterns WHERE project_id = %s ORDER BY added_at, pattern", (project_id,)
    ).fetchall()
    return [row["pattern"] for row in rows]


def _addable(pattern: str) -> str:
    """The pattern as it is kept, refused when it is unusable or already one of the built-in list."""
    written = usable(pattern)
    if written in NEVER_LOCK:
        raise Refused(f"{written!r} is built in: it already never locks in every project.")
    return written


def _end_locks_matching(conn: Conn, project_id: str, pattern: str) -> list[tuple[str, str, int]]:
    """End each lock in the project on a file this pattern matches, and give each one's repository, path and holder's
    session ID. The file never locks from here on, so its lock would block nobody and only be listed."""
    held = conn.execute("SELECT repository, path FROM locks WHERE project_id = %s", (project_id,)).fetchall()
    ended: list[tuple[str, str, int]] = []
    for lock in held:
        if matching([pattern], lock["path"]) is None:
            continue
        gone = conn.execute(
            "DELETE FROM locks WHERE project_id = %s AND repository = %s AND path = %s RETURNING session_id",
            (project_id, lock["repository"], lock["path"]),
        ).fetchone()
        if gone is not None:
            ended.append((lock["repository"], lock["path"], gone["session_id"]))
    return ended


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
        here on, so the lock would block nobody and only be listed. Its holder is told once, as a takeover's old
        holder is (`Locks.waiting_notices`)."""
        project_id = self._changeable_by(caller)
        added = NeverLockPattern(_addable(pattern), caller.member_id, self._clock())
        with self._db.transaction() as conn:
            self._write(conn, project_id, added)
            for repository, path, holder in _end_locks_matching(conn, project_id, added.pattern):
                self._tell_holder(conn, caller, added, repository, path, holder)
        self._record(caller, NEVER_LOCK_PATTERN_ADDED, project_id, added.pattern)
        return added

    def _write(self, conn: Conn, project_id: str, added: NeverLockPattern) -> None:
        """Keep the pattern for the project, refusing one it already has."""
        kept = conn.execute(
            "INSERT INTO never_lock_patterns (project_id, pattern, added_by, added_at) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (project_id, pattern) DO NOTHING RETURNING pattern",
            (project_id, added.pattern, added.added_by, added.added_at),
        ).fetchone()
        if kept is None:
            raise Refused(f"{added.pattern!r} is already one of this project's never-lock patterns.")

    def _tell_holder(
        self, conn: Conn, caller: Caller, added: NeverLockPattern, repository: str, path: str, holder: int
    ) -> None:
        """Keep, for the holder of a lock the added pattern ended, the word that it ended and who added the pattern.
        The holder is told once. One whose session has ended or gone idle never reads it: what is waiting for a
        session is cleared when it is found gone."""
        conn.execute(
            "INSERT INTO locks_ended_by_pattern"
            " (session_id, repository, path, pattern, by_name, by_member_id, ended_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (holder, repository, path, added.pattern, caller.member.name, caller.member_id, added.added_at),
        )

    def remove(self, caller: Caller, pattern: str) -> str:
        """Remove one of the caller's project's own patterns, and give it back as it was kept. Files it matched lock
        again."""
        project_id = self._changeable_by(caller)
        # Read as `usable` reads a pattern being added, but not refused as unusable: one that isn't kept is told so.
        written = slashed(pattern)
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
        if not self._identity.looks_after(caller.member, project_id):
            raise Refused(
                "Only this project's leads and the team's admins can add or remove its never-lock patterns. Any "
                "member of the project can read them, by calling never_lock with nothing."
            )
        return project_id

    def _record(self, caller: Caller, change: str, project_id: str, pattern: str) -> None:
        detail = {"agent": caller.agent} if caller.agent is not None else {}
        self._audit.record(change, member=caller.member, project_id=project_id, target=pattern, detail=detail)
