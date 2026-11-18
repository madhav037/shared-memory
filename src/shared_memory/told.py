"""A session's told record (CONTEXT.md: Told record): everything Shared Memory told it, in order and with when.

It holds the session's briefing as delivered and each memory recall added to a prompt, each with the memory
repository's head commit when it was told, so a memory's text then is its version at that commit (`/memory/version`).
It never holds what the member typed. Records older than `Settings.told_days` are pruned as new ones are written, and
never read back. It is the record of what was said; `recall_told` (recall.py) stays the told-once bookkeeping, and is
cleared when a session ends, where this is kept.

The interface:

- `briefed(session, text)`: the briefing as it was delivered to the session.
- `recalled(session, memories)`: the memories one recall added to the session's prompt, in the order told.
- `of(caller, number)`: one of the caller's project's sessions and its told record, oldest first, for the session's own
  member, the project's leads and the team's admins (`may_read`); refused to anyone else.
- `most_recalled(under, within)`: the memories under a folder that recall told in the most sessions lately, with how
  many sessions each, for project health's most relied on. Reach is the asker's to check.
- `recent(caller)`: the sessions of the caller's project from the last `told_days` whose told record the caller may
  read, the most recently seen first, each with how many memories it was told (#566).

Only this module reads the `session_told` table. A row refers to its session by `Session.id`; sessions are never
deleted, so an ended session keeps its record.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity
from shared_memory.sessions import Session, Sessions
from shared_memory.store import MemoryStore

Kind = Literal["briefing", "recall"]
BRIEFING: Kind = "briefing"
RECALL: Kind = "recall"

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_told (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES sessions(id),
    -- briefing or recall.
    kind TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL,
    -- The memory repository's head commit when it was told; None before memory's first save.
    head_commit TEXT,
    -- The briefing as delivered, for a briefing.
    briefing TEXT,
    -- The memory told, for a recall: its path, its title then, and the heading of the section told.
    path TEXT,
    title TEXT,
    section TEXT
);
CREATE INDEX IF NOT EXISTS session_told_by_session ON session_told (session_id, id);
CREATE INDEX IF NOT EXISTS session_told_by_at ON session_told (at);
"""


class NotItsReader(Refused):
    """A session's told record is for its own member, its project's leads and the team's admins."""

    def __init__(self) -> None:
        super().__init__(
            "Only a session's own member, its project's leads and the team's admins can read what it was told."
        )


@dataclass(frozen=True)
class ToldMemory:
    """A memory as recall told it: where it sits, its title, and the heading of the section told."""

    path: str
    title: str
    section: str


@dataclass(frozen=True)
class Told:
    """One thing a session was told: a briefing, with its text, or a memory a recall added."""

    kind: Kind
    at: datetime
    commit: str | None
    briefing: str | None = None
    memory: ToldMemory | None = None


# The most recent sessions listed, so a lead of a busy project is not sent a month of them at once.
RECENT_LIMIT = 100


@dataclass(frozen=True)
class RecentSession:
    """One of a project's recent sessions: whether it is active now, and how many memories recall told it."""

    session: Session
    active: bool
    memories_told: int


class ToldRecord:
    def __init__(
        self, settings: Settings, db: Database, store: MemoryStore, sessions: Sessions, identity: Identity, clock: Clock
    ) -> None:
        self._kept = timedelta(days=settings.told_days)
        self._db = db
        self._store = store
        self._sessions = sessions
        self._identity = identity
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def briefed(self, session: Session, text: str) -> None:
        """Record the briefing as it was delivered to the session."""
        self._add(session, [(BRIEFING, text, None, None, None)])

    def recalled(self, session: Session, memories: Sequence[ToldMemory]) -> None:
        """Record the memories one recall added to the session's prompt, in the order told."""
        self._add(session, [(RECALL, None, one.path, one.title, one.section) for one in memories])

    def _add(self, session: Session, rows: list[tuple[Kind, str | None, str | None, str | None, str | None]]) -> None:
        if not rows:
            return
        now, head = self._clock(), self._store.head()
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM session_told WHERE at < %s", (now - self._kept,))
            conn.cursor().executemany(
                "INSERT INTO session_told (session_id, kind, at, head_commit, briefing, path, title, section)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [(session.id, kind, now, head, briefing, path, title, section) for kind, briefing, path, title, section in rows],
            )

    def most_recalled(self, under: str, within: timedelta) -> list[tuple[str, int]]:
        """Each memory under the folder that a recall told within the last `within` (and the record still keeps), with
        how many sessions it was told in, the most first. A session counts once however many of its sections it was
        told."""
        since = self._clock() - min(within, self._kept)
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT path, COUNT(DISTINCT session_id) AS sessions FROM session_told"
                " WHERE kind = %s AND starts_with(path, %s) AND at >= %s"
                " GROUP BY path ORDER BY sessions DESC, path",
                (RECALL, under.rstrip("/") + "/", since),
            ).fetchall()
        return [(row["path"], row["sessions"]) for row in rows]

    def may_read(self, caller: Caller, session: Session) -> bool:
        """Whether the caller may read this session's told record: it is their own, or they look after its project."""
        return session.member_id == caller.member_id or self._identity.looks_after(caller.member, session.project_id)

    def recent(self, caller: Caller) -> list[RecentSession]:
        """The sessions of the caller's project that were active in the last `told_days` and whose told record the
        caller may read, the most recently seen first, at most `RECENT_LIMIT`: their own, or every one when they look
        after the project. Each with how many memories recall told it in that time."""
        project = caller.require_project()
        looks_after = self._identity.looks_after(caller.member, project.project_id)
        listed = [
            (session, active)
            for session, active in self._sessions.lately(project.project_id, self._kept)
            if looks_after or session.member_id == caller.member_id
        ][:RECENT_LIMIT]
        if not listed:
            return []
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT session_id, count(*) AS told FROM session_told"
                " WHERE session_id = ANY(%s) AND kind = %s AND at >= %s GROUP BY session_id",
                ([session.id for session, _ in listed], RECALL, self._clock() - self._kept),
            ).fetchall()
        told = {row["session_id"]: row["told"] for row in rows}
        return [RecentSession(session, active, told.get(session.id, 0)) for session, active in listed]

    def of(self, caller: Caller, number: int) -> tuple[Session, list[Told]]:
        """One of the session's of the caller's project, by its number, and what it was told, oldest first. Refused,
        alike, when the project has no such session and when the caller may not read it."""
        project = caller.require_project()
        session = self._sessions.numbered(project.project_id, number)
        if session is None or not self.may_read(caller, session):
            raise NotItsReader()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT kind, at, head_commit, briefing, path, title, section FROM session_told"
                " WHERE session_id = %s AND at >= %s ORDER BY id",
                (session.id, self._clock() - self._kept),
            ).fetchall()
        return session, [
            Told(
                kind=cast(Kind, row["kind"]),
                at=row["at"],
                commit=row["head_commit"],
                briefing=row["briefing"],
                memory=ToldMemory(row["path"], row["title"], row["section"]) if row["path"] is not None else None,
            )
            for row in rows
        ]
