"""Standby (ADR-0027): a session awaiting an answer stands by, and its coding agent hears its news without its member
typing.

A standby belongs to a session, and a session has at most one: starting one ends the session's earlier standby, which
answers "replaced". While it is held, it checks every `Settings.standby_check_seconds` (2 s) for news for its session,
asking the one place every hook asks (`waiting_for` in `app.py`), which marks what it hands over told. As soon as there
is any, it answers with that news. Otherwise it ends at its cap, `Settings.standby_cap_minutes` and never longer than
the project's wait, measured against the server's clock, answering "nothing yet" with the time left of the project's
wait; or at the session's next prompt, which ends it (`end`) and answers "your member moved on", the prompt hook
delivering the news itself.

It is worked out against Postgres, so any worker can hold a standby while another records the answer or the prompt
(ADR-0013): `standbys` keeps each session's held standby, under the random name of the request holding it, and a
holder that finds another name there has been replaced. The request is held without a worker thread: it sleeps on the
event loop between checks, and each check's queries run on a worker thread.

What other modules stand on, all of it on `Standbys`:

- `hold(session, news, awaits=(), seconds=None, gone=None)`: hold a standby for this session until it ends, and give
  how it ended. `news` is what the session would be told now, marking it told (`waiting_for`); `awaits` the member IDs
  whose answer it awaits, kept for the console; `seconds` a shorter hold than the cap, for a held tool call; `gone`
  says the asker has gone away, which ends the standby before it can take news nobody would receive.
- `end(session)`: the session's member moved on: its next prompt ends its standby.
- `in_project(project_id)`: the standbys held now in a project, each with its session's id and whose answer it awaits.
  Whether the session is active, and whether the asker may reach the project, is the asker's to check.
"""

from __future__ import annotations

import math
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

import anyio
import anyio.to_thread

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.sessions import Session, Sessions

SCHEMA = """
-- Each session's held standby: at most one, under the name of the request holding it.
CREATE TABLE IF NOT EXISTS standbys (
    session_id BIGINT PRIMARY KEY REFERENCES sessions(id),
    project_id TEXT NOT NULL,
    request TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    -- When it ends with nothing yet, by the server's clock.
    ends_at TIMESTAMPTZ NOT NULL,
    -- The member IDs of the members whose answer the session awaits, for the console.
    awaits TEXT[] NOT NULL DEFAULT '{}',
    -- The session's next prompt arrived: its member moved on.
    moved_on BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS standbys_by_project ON standbys (project_id);
"""


class Ending(StrEnum):
    """How a standby ended, as its answer names it."""

    NEWS = "news"
    NOTHING_YET = "nothing_yet"
    REPLACED = "replaced"
    MOVED_ON = "moved_on"
    # The asker went away before anything else ended it; nobody reads this answer.
    GONE = "gone"


@dataclass(frozen=True)
class Standby:
    """A standby held now."""

    session_id: int
    started_at: datetime
    ends_at: datetime
    awaits: tuple[str, ...]


def _minutes(left: timedelta) -> str:
    minutes = math.ceil(left.total_seconds() / 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


@dataclass(frozen=True)
class Ended:
    """How a standby ended, and what it hands over: the session's news, or with nothing yet, the time left of the
    project's wait."""

    ending: Ending
    news: list[str] = field(default_factory=list)
    wait_left: timedelta | None = None

    @property
    def message(self) -> str:
        """What the coding agent is told."""
        if self.ending == Ending.NEWS:
            return "\n\n".join(self.news)
        if self.ending == Ending.NOTHING_YET:
            left = self.wait_left or timedelta()
            then = (
                f"{_minutes(left)} are left of the project's wait: you may stand by once more."
                if left > timedelta()
                else "The project's wait has passed."
            )
            return f"[standby] Nothing yet: no news came for this session while it stood by. {then} Tell your member."
        if self.ending == Ending.REPLACED:
            return "[standby] A newer standby of this session replaced this one, and hears its news instead."
        if self.ending == Ending.MOVED_ON:
            return (
                "[standby] Your member moved on: their next prompt ended this standby, and any news for this session "
                "came with that prompt."
            )
        return "[standby] Ended: the request went away."


class Standbys:
    def __init__(
        self, settings: Settings, db: Database, sessions: Sessions, wait: Callable[[str], int], clock: Clock
    ) -> None:
        """`wait` gives a project's wait in minutes (`Gates.wait`)."""
        self._cap = timedelta(minutes=settings.standby_cap_minutes)
        self._every = settings.standby_check_seconds
        self._db = db
        self._wait = wait
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)
        sessions.on_gone(self._clear)

    @staticmethod
    def _clear(conn: Conn, ids: Sequence[int]) -> None:
        conn.execute("DELETE FROM standbys WHERE session_id = ANY(%s)", (list(ids),))

    async def hold(
        self,
        session: Session,
        news: Callable[[], list[str]],
        awaits: Sequence[str] = (),
        seconds: float | None = None,
        gone: Callable[[], Awaitable[bool]] | None = None,
    ) -> Ended:
        """Hold a standby for this session until it ends, replacing any earlier one, and give how it ended. Each check
        reads the standby's row, then whether the asker is gone, then the news, then the clock, and sleeps between."""
        request = secrets.token_hex(8)
        wait = await anyio.to_thread.run_sync(self._start, session, request, tuple(awaits), seconds)
        ended: Ended | None = None
        try:
            while True:
                ended = await anyio.to_thread.run_sync(self._still_held, session, request)
                if ended is not None:
                    return ended
                if gone is not None and await gone():
                    ended = Ended(Ending.GONE)
                    return ended
                found = await anyio.to_thread.run_sync(news)
                if found:
                    ended = Ended(Ending.NEWS, found)
                    return ended
                now = self._clock()
                if now >= wait.ends_at:
                    ended = Ended(Ending.NOTHING_YET, wait_left=max(timedelta(), wait.started_at + wait.whole - now))
                    return ended
                await anyio.sleep(self._every)
        finally:
            if ended is None or ended.ending != Ending.REPLACED:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(self._let_go, session, request)

    def _start(self, session: Session, request: str, awaits: tuple[str, ...], seconds: float | None) -> _Held:
        """Keep this request as the session's standby, in place of any earlier one, and say how long it is held."""
        now = self._clock()
        whole = timedelta(minutes=self._wait(session.project_id))
        held = min(self._cap, whole)
        if seconds is not None:
            held = min(held, timedelta(seconds=max(0.0, seconds)))
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO standbys (session_id, project_id, request, started_at, ends_at, awaits)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (session_id) DO UPDATE SET request = EXCLUDED.request,"
                " started_at = EXCLUDED.started_at, ends_at = EXCLUDED.ends_at, awaits = EXCLUDED.awaits,"
                " moved_on = FALSE",
                (session.id, session.project_id, request, now, now + held, list(awaits)),
            )
        return _Held(now, now + held, whole)

    def _still_held(self, session: Session, request: str) -> Ended | None:
        """None while this request is still the session's standby; otherwise how it ended: replaced by a newer one, or
        ended by the session's next prompt or by the session's end."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT request, moved_on FROM standbys WHERE session_id = %s", (session.id,)
            ).fetchone()
        if row is None or row["moved_on"]:
            return Ended(Ending.MOVED_ON)
        if row["request"] != request:
            return Ended(Ending.REPLACED)
        return None

    def _let_go(self, session: Session, request: str) -> None:
        """This request no longer holds the session's standby."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM standbys WHERE session_id = %s AND request = %s", (session.id, request))

    def end(self, session: Session) -> None:
        """The session's member moved on: its next prompt ends its standby, if one is held."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE standbys SET moved_on = TRUE WHERE session_id = %s AND NOT moved_on", (session.id,)
            )

    def in_project(self, project_id: str) -> list[Standby]:
        """The standbys held now in a project's sessions, the oldest first. One whose request was lost with its worker
        counts as held until its end."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT session_id, started_at, ends_at, awaits FROM standbys"
                " WHERE project_id = %s AND NOT moved_on AND ends_at > %s ORDER BY started_at, session_id",
                (project_id, self._clock()),
            ).fetchall()
        return [Standby(row["session_id"], row["started_at"], row["ends_at"], tuple(row["awaits"])) for row in rows]


@dataclass(frozen=True)
class _Held:
    """How long one standby is held: from its start to its end, out of the project's whole wait."""

    started_at: datetime
    ends_at: datetime
    whole: timedelta
