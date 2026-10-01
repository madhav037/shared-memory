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
- `waiting_notices(session)`: what a session is told once, on its next prompt.
- `idle_after`: the idle time, from `Settings.session_idle_minutes`.

A module keeping rows per session refers to `Session.id`. Only this module reads the `sessions` table.
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
from shared_memory.identity import Caller

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

CREATE INDEX IF NOT EXISTS sessions_not_ended ON sessions (project_id, last_seen_at) WHERE ended_at IS NULL;
"""

# The longest identifier kept. Coding agents send a UUID or something as short.
IDENTIFIER_LIMIT = 100

BACK_FROM_IDLE = (
    "[session] This session made no call to Shared Memory for longer than a session may sit idle, so its activity "
    "and locks ended. State its activity again, and take a file's lock again before editing it: another session may "
    "hold it now."
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
    # The coding agent it runs in, once a tool call has reported it; a hook does not say.
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
    def __init__(self, settings: Settings, db: Database, clock: Clock) -> None:
        self._db = db
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

    def touch(self, caller: Caller, identifier: str) -> Session:
        """The calling session, seen now: started if the server doesn't know it, active again if it had ended or gone
        idle. One back from idle has lost its activity and locks, and is told so on its next prompt."""
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
                (*key, caller.repository, caller.agent, now, now),
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
                    " back_from_idle = (back_from_idle OR %s) AND NOT %s,"
                    " repository = COALESCE(%s, repository), agent = COALESCE(%s, agent)"
                    " WHERE id = %s RETURNING id, repository, agent, started_at",
                    (now, ended, now, idle, ended, caller.repository, caller.agent, known["id"]),
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
                "SELECT s.id, s.identifier, m.member_id, m.name, s.project_id, s.repository, s.agent, s.started_at,"
                " s.last_seen_at FROM sessions s JOIN members m ON m.id = s.member_id"
                " WHERE s.project_id = %s AND s.ended_at IS NULL AND s.last_seen_at > %s ORDER BY s.started_at, s.id",
                (project_id, self._clock() - self.idle_after),
            ).fetchall()
        return [_session(row) for row in rows]

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
        """What this session is told once, with its next prompt: that it is back from idle, so its activity and
        locks ended. Asking marks it told."""
        with self._db.transaction() as conn:
            told = conn.execute(
                "UPDATE sessions SET back_from_idle = FALSE WHERE id = %s AND back_from_idle RETURNING id",
                (session.id,),
            ).fetchone()
        return [BACK_FROM_IDLE] if told is not None else []

    def end_unreachable(self, conn: Conn, caller: Caller) -> Callable[[], None]:
        """End every session whose member can no longer reach its project: removed from the team, or shut out of a
        restricted project. Identity calls this inside the transaction of any change that may have cost a member a
        project (`Identity.on_access_lost`), so the change and the sessions' end happen together or not at all."""
        rows = conn.execute(
            "UPDATE sessions s SET ended_at = %s, back_from_idle = FALSE FROM members m, projects p"
            " WHERE m.id = s.member_id AND p.project_id = s.project_id AND p.team_id = %s AND s.ended_at IS NULL"
            " AND (m.removed_at IS NOT NULL OR (p.restricted AND NOT m.is_owner AND NOT m.is_admin"
            " AND NOT EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = m.id)"
            " AND NOT EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = m.id)"
            ")) RETURNING s.id",
            (self._clock(), caller.member.team_pk),
        ).fetchall()
        self._tell_gone(conn, [row["id"] for row in rows])
        return lambda: None


def _session(row: dict[str, Any]) -> Session:
    return Session(
        id=row["id"],
        identifier=row["identifier"],
        member_id=row["member_id"],
        member_name=row["name"],
        project_id=row["project_id"],
        repository=row["repository"],
        agent=row["agent"],
        started_at=row["started_at"],
        last_seen_at=row["last_seen_at"],
    )
