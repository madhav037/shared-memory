"""When each memory was last used, and which memories are possibly outdated (CONTEXT.md: Outdated memory).

A memory is used when recall adds it to a prompt or a coding agent opens it with `read`; nothing else counts. Saving a
memory starts its clock again. Last use lives in Postgres, never in the memory's file (ADR-0002), in `memory_uses`,
which only this module reads. A memory is possibly outdated when it is active, not pinned, and unused for longer than
`Settings.outdated_after_days`. Nothing is done about it automatically: it is only a label.

The interface:

- `used(team, paths)`: those memories were used now.
- `possibly_outdated(team, statuses)`: which of these memories (path to status) are possibly outdated.
- `last_used(team, path)`: when one memory was last used, or None.
- `check(team, path)`: what an agent is told to do about a possibly outdated memory.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.memory import Memory
from shared_memory.store import MemoryStore

SCHEMA = """
CREATE TABLE memory_uses (
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    last_used_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (team, path)
);
"""

_RECORD = (
    "INSERT INTO memory_uses (team, path, last_used_at) VALUES (%s, %s, %s)"
    " ON CONFLICT (team, path) DO UPDATE SET last_used_at = GREATEST(memory_uses.last_used_at, EXCLUDED.last_used_at)"
)

# Which of a team's paths are pinned, the memory itself or the topic folder it sits in: the briefing's to answer.
PinnedAmong = Callable[[str, Iterable[str]], set[str]]


class Uses:
    def __init__(
        self, settings: Settings, db: Database, store: MemoryStore, pinned_among: PinnedAmong, clock: Clock
    ) -> None:
        self._db = db
        self._pinned_among = pinned_among
        self._clock = clock
        self._after = timedelta(days=settings.outdated_after_days)
        if db.sets_up:
            self._set_up(store)

    def _set_up(self, store: MemoryStore) -> None:
        """Make the table. Made for the first time, every memory already on disk counts as used today."""
        with self._db.transaction() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('memory_uses'))")
            if conn.execute("SELECT 1 FROM pg_tables WHERE tablename = 'memory_uses' AND schemaname = current_schema()").fetchone():
                return
            conn.execute(SCHEMA)
            now = self._clock()
            for team in store.teams():
                rows = [(team, str(path), now) for _, memories in store.walk(team, PurePosixPath()) for path, _ in memories]
                if rows:
                    conn.cursor().executemany(_RECORD, rows)

    def used(self, team: str, paths: Iterable[str]) -> None:
        rows = [(team, path, self._clock()) for path in dict.fromkeys(paths)]
        if not rows:
            return
        with self._db.transaction() as conn:
            conn.cursor().executemany(_RECORD, rows)

    def last_used(self, team: str, path: str) -> datetime | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT last_used_at FROM memory_uses WHERE team = %s AND path = %s", (team, path)
            ).fetchone()
        return None if row is None else row["last_used_at"]

    def possibly_outdated(self, team: str, statuses: Mapping[str, str]) -> set[str]:
        """Which of these memories, given as path to status, are possibly outdated. A memory with no last use isn't."""
        active = [path for path, status in statuses.items() if status == "active"]
        if not active:
            return set()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT path FROM memory_uses WHERE team = %s AND path = ANY(%s) AND last_used_at < %s",
                (team, active, self._clock() - self._after),
            ).fetchall()
        unused = {row["path"] for row in rows}
        return unused - self._pinned_among(team, unused) if unused else set()

    def check(self, team: str, path: str) -> str:
        """What a coding agent is told about a possibly outdated memory: how long it has gone unused, and what to do."""
        last = self.last_used(team, path)
        days = (self._clock() - last).days if last is not None else self._after.days
        return (
            f"Possibly outdated: no coding agent has recalled or read this memory for {days} days. Check it still "
            "holds against the code before relying on it. If it no longer holds, tell the member, who can retire it."
        )

    @contextmanager
    def on_change(
        self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> Iterator[None]:
        """Saving a memory starts its clock again; deleting one forgets it. Committed once the save has landed."""
        with self._db.transaction() as conn:
            now = self._clock()
            if writes:
                conn.cursor().executemany(_RECORD, [(team, str(path), now) for path in writes])
            gone = [str(path) for path in deletes]
            if gone:
                conn.execute("DELETE FROM memory_uses WHERE team = %s AND path = ANY(%s)", (team, gone))
            yield
