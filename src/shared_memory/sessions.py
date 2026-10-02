"""The sessions the server knows: each running conversation of a member's coding agent in one project (ADR-0018).

A session is told apart by the identifier its coding agent's hooks send, kept per member and project. It is active
from its first call until its session-end hook, or until it has made no call for the idle time. Active is worked out
from the clock on every read: nothing sweeps, so every worker agrees (ADR-0013).

What other modules stand on, all of it on `Sessions`:

- `touch(caller, identifier)`: the calling session, from a hook or from a tool that takes `session`. It starts a
  session the server doesn't know, moves a known one's last-seen time, and brings back one that ended or went idle.
- `start(caller)`: a session under an identifier made here, for an agent that was never told one.
- `end(caller, identifier)`: the session-end hook.
- `active(project_id)`: a project's active sessions, oldest first.
- `still_active(ids)`: which of these sessions are active, for a module that keeps something per session and must
  count an ended or idle session's as gone wherever it reads it.
- `on_gone(listener)`: called, inside the transaction, with the sessions that just ended or were found back from
  idle, so a module clears what it kept for them. A session that goes idle and never calls again is never reported:
  `still_active` is what says it is gone.
- `waiting_notices(session)`: what a session is told once: that it is back from idle, or back after it had ended.
- `idle_after`: the idle time, from `Settings.session_idle_minutes`.

A module keeping rows per session refers to `Session.id`. Only this module reads the `sessions` table, and it reads
members and projects through `Identity`.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES members(id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    -- What the session's coding agent sends in its hook payloads, or what `briefing` made up for it.
    identifier TEXT NOT NULL,
    repository TEXT,
    agent TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    -- It called again after going idle and has not yet been told that its activity and locks ended.
    back_from_idle BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (member_id, project_id, identifier)
);

-- It called again after it had ended and has not yet been told that its activity and locks ended.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS back_from_end BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS sessions_not_ended ON sessions (project_id, last_seen_at) WHERE ended_at IS NULL;
"""

# The longest identifier kept. Coding agents send a UUID or something as short.
IDENTIFIER_LIMIT = 100

BACK_FROM_IDLE = (
    "[session] This session made no call to Shared Memory for longer than a session may sit idle, so its activity "
    "and locks ended. State its activity again, and take a file's lock again before editing it: another session may "
    "hold it now."
)

BACK_FROM_END = (
    "[session] This session ended and has now started again, so its activity and locks ended. State its activity "
    "again, and take a file's lock again before editing it: another session may hold it now."
)

# Called inside the transaction that found these sessions gone, with their ids.
Gone = Callable[[Conn, Sequence[int]], None]


@dataclass(frozen=True)
class Session:
    """One session as the server knows it."""

    # What another module's rows refer to.
    id: int
    identifier: str
    member_id: str
    member_name: str
    project_id: str
    repository: str | None
    # The coding agent it runs in, once a tool call has reported it or a hook has said which it came from.
    agent: str | None
    started_at: datetime
    last_seen_at: datetime


class UnusableIdentifier(Refused):
    """A session identifier the server will not keep."""


def usable(identifier: object) -> str | None:
    """A session identifier as it is kept, or None for one that can't be: not text, empty or too long."""
    if not isinstance(identifier, str):
        return None
    cleaned = identifier.strip()
    return cleaned if cleaned and len(cleaned) <= IDENTIFIER_LIMIT else None


def briefing_line(session: Session) -> str:
    """What tells a coding agent its session's identifier, with its briefing."""
    return (
        f"This session's identifier in Shared Memory is `{session.identifier}`. Pass it as `session` to the Shared "
        "Memory tools that take one."
    )


class Sessions:
    def __init__(self, settings: Settings, db: Database, identity: Identity, clock: Clock) -> None:
        self._db = db
        self._identity = identity
        self._clock = clock
        self.idle_after = timedelta(minutes=settings.session_idle_minutes)
        self._gone: list[Gone] = []
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def on_gone(self, listener: Gone) -> None:
        """Have a module told when sessions end or are found back from idle. A session may be reported twice (back
        from idle, then ended), so a listener clears what it finds and expects nothing."""
        self._gone.append(listener)

    def _tell_gone(self, conn: Conn, ids: Sequence[int]) -> None:
        if ids:
            for listener in self._gone:
                listener(conn, ids)

    def start(self, caller: Caller) -> Session:
        """Start a session under an identifier made here, for a coding agent whose hooks told it none."""
        return self.touch(caller, secrets.token_hex(8))

    def touch(self, caller: Caller, identifier: str, hooked_by: str | None = None) -> Session:
        """The calling session, seen now: started if the server doesn't know it, active again if it had ended or gone
        idle. One back from idle, or back after it had ended, has lost its activity and locks, and is told so once
        (`waiting_notices`). `hooked_by` is the coding agent a hook says it runs in, kept only for a session whose
        agent no tool call has reported: the caller's own agent, which a tool call reports, replaces it."""
        project = caller.require_project()
        kept = usable(identifier)
        if kept is None:
            raise UnusableIdentifier(
                f"A session identifier is 1-{IDENTIFIER_LIMIT} characters. Pass as `session` the identifier this "
                "session's briefing named, or call briefing without one to be given one."
            )
        now = self._clock()
        key = (caller.member.pk, project.project_id, kept)
        with self._db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO sessions (member_id, project_id, identifier, repository, agent, started_at, last_seen_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (member_id, project_id, identifier) DO NOTHING"
                " RETURNING id, repository, agent, started_at",
                (*key, caller.repository, caller.agent or hooked_by, now, now),
            ).fetchone()
            if row is None:
                known = conn.execute(
                    "SELECT id, last_seen_at, ended_at FROM sessions"
                    " WHERE member_id = %s AND project_id = %s AND identifier = %s FOR UPDATE",
                    key,
                ).fetchone()
                assert known is not None
                ended = known["ended_at"] is not None
                idle = not ended and now - known["last_seen_at"] >= self.idle_after
                if idle:
                    self._tell_gone(conn, [known["id"]])
                row = conn.execute(
                    "UPDATE sessions SET last_seen_at = %s, ended_at = NULL,"
                    " started_at = CASE WHEN %s THEN %s ELSE started_at END,"
                    " back_from_idle = (back_from_idle OR %s) AND NOT %s, back_from_end = back_from_end OR %s,"
                    " repository = COALESCE(%s, repository), agent = COALESCE(%s, agent, %s)"
                    " WHERE id = %s RETURNING id, repository, agent, started_at",
                    (now, ended, now, idle, ended, ended, caller.repository, caller.agent, hooked_by, known["id"]),
                ).fetchone()
                assert row is not None
        return Session(
            id=row["id"],
            identifier=kept,
            member_id=caller.member_id,
            member_name=caller.member.name,
            project_id=project.project_id,
            repository=row["repository"],
            agent=row["agent"],
            started_at=row["started_at"],
            last_seen_at=now,
        )

    def end(self, caller: Caller, identifier: str) -> None:
        """End the calling session, as its session-end hook asks. One the server doesn't know, or that has already
        ended, is left as it is."""
        project = caller.require_project()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "UPDATE sessions SET ended_at = %s, back_from_idle = FALSE"
                " WHERE member_id = %s AND project_id = %s AND identifier = %s AND ended_at IS NULL RETURNING id",
                (self._clock(), caller.member.pk, project.project_id, identifier.strip()),
            ).fetchall()
            self._tell_gone(conn, [row["id"] for row in rows])

    def active(self, project_id: str) -> list[Session]:
        """A project's active sessions, oldest first. Whether the asker may reach the project is the asker's to
        check."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, identifier, member_id, project_id, repository, agent, started_at, last_seen_at FROM sessions"
                " WHERE project_id = %s AND ended_at IS NULL AND last_seen_at > %s ORDER BY started_at, id",
                (project_id, self._clock() - self.idle_after),
            ).fetchall()
        members = self._identity.named(row["member_id"] for row in rows)
        return [_session(row, *members[row["member_id"]]) for row in rows]

    def still_active(self, ids: Iterable[int], conn: Conn | None = None) -> set[int]:
        """Which of these sessions are active now. Pass the connection of a transaction already open to ask within
        it."""
        asked = list(ids)
        if not asked:
            return set()
        query = "SELECT id FROM sessions WHERE id = ANY(%s) AND ended_at IS NULL AND last_seen_at > %s"
        values = (asked, self._clock() - self.idle_after)
        if conn is not None:
            return {row["id"] for row in conn.execute(query, values).fetchall()}
        with self._db.transaction() as own:
            return {row["id"] for row in own.execute(query, values).fetchall()}

    def waiting_notices(self, session: Session) -> list[str]:
        """What this session is told once, with its next prompt or the answer of its next tool call: that it is back
        from idle, or back after it had ended, so its activity and locks ended. Asking marks it told."""
        with self._db.transaction() as conn:
            told = conn.execute(
                "WITH was AS (SELECT id, back_from_end FROM sessions"
                " WHERE id = %s AND (back_from_idle OR back_from_end) FOR UPDATE)"
                " UPDATE sessions s SET back_from_idle = FALSE, back_from_end = FALSE FROM was WHERE s.id = was.id"
                " RETURNING was.back_from_end",
                (session.id,),
            ).fetchone()
        if told is None:
            return []
        return [BACK_FROM_END if told["back_from_end"] else BACK_FROM_IDLE]

    def end_unreachable(self, conn: Conn, caller: Caller) -> Callable[[], None]:
        """End every session whose member can no longer reach its project: removed from the team, or shut out of a
        restricted project. Identity calls this inside the transaction of any change that may have cost a member a
        project (`Identity.on_access_lost`), so the change and the sessions' end happen together or not at all."""
        open_pairs = conn.execute("SELECT DISTINCT member_id, project_id FROM sessions WHERE ended_at IS NULL").fetchall()
        lost = self._identity.cannot_reach(
            conn, caller.member.team_pk, [(row["member_id"], row["project_id"]) for row in open_pairs]
        )
        if not lost:
            return lambda: None
        rows = conn.execute(
            "UPDATE sessions s SET ended_at = %s, back_from_idle = FALSE"
            " FROM unnest(%s::bigint[], %s::text[]) AS x(member_id, project_id)"
            " WHERE s.member_id = x.member_id AND s.project_id = x.project_id AND s.ended_at IS NULL RETURNING s.id",
            (self._clock(), [pk for pk, _ in lost], [project_id for _, project_id in lost]),
        ).fetchall()
        self._tell_gone(conn, [row["id"] for row in rows])
        return lambda: None


def _session(row: dict[str, Any], member_id: str, member_name: str) -> Session:
    return Session(
        id=row["id"],
        identifier=row["identifier"],
        member_id=member_id,
        member_name=member_name,
        project_id=row["project_id"],
        repository=row["repository"],
        agent=row["agent"],
        started_at=row["started_at"],
        last_seen_at=row["last_seen_at"],
    )
