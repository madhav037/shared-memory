"""Popular memory (CONTEXT.md): a personal memory enough other members' sessions have read, whose author is prompted to
promote it.

A memory is read when a coding agent opens it with `read`; recall never shows anyone another member's personal memory,
so reads are what count (#538). Each member counts once however often they read it, and the author never counts. A
personal memory is popular when at least `Settings.popular_members` other members read it within the last
`Settings.popular_window_days`. Its author's next briefing in its project names it and points at `promote`, which
still runs the contradiction check (ADR-0004). It is named again only once its count of readers is at least
`Settings.popular_reprompt_factor` times the count it was named with. A memory that is not active (promoted, retired)
or is in doubt is never named.

Who read what lives in Postgres, never in the memory's file (ADR-0002):

- `memory_readers`: one row per memory and reading member, with when they last read it. Rows older than the window are
  pruned as reads are recorded.
- `popular_prompts`: one row per memory its author was prompted about, with the count of readers named then.

Only this module reads those two tables.

The interface:

- `read_by(caller, path)`: the caller's session read this memory now.
- `briefing_notices(caller)`: the lines naming the caller's popular memories in their project not yet named at this
  count, recorded as named.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import PurePosixPath

from shared_memory.challenges import Challenges
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.fence import escape
from shared_memory.identity import Caller
from shared_memory.memory import Memory, locate
from shared_memory.store import MemoryStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_readers (
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    member_id TEXT NOT NULL,
    read_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (team, path, member_id)
);
CREATE INDEX IF NOT EXISTS memory_readers_read_at ON memory_readers (read_at);
CREATE TABLE IF NOT EXISTS popular_prompts (
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    readers INTEGER NOT NULL,
    prompted_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (team, path)
);
"""


class Popularity:
    def __init__(self, settings: Settings, db: Database, store: MemoryStore, challenges: Challenges, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._challenges = challenges
        self._clock = clock
        self._window = timedelta(days=settings.popular_window_days)
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def read_by(self, caller: Caller, path: str) -> None:
        """The caller's session read this memory. Only another member's personal memory is worth counting."""
        try:
            location = locate(path)
        except Refused:
            return
        if location.level != "personal" or location.member_id == caller.member_id:
            return
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM memory_readers WHERE team = %s AND read_at < %s", (caller.team, now - self._window))
            conn.execute(
                "INSERT INTO memory_readers (team, path, member_id, read_at) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (team, path, member_id) DO UPDATE SET read_at = EXCLUDED.read_at",
                (caller.team, str(location.path), caller.member_id, now),
            )

    def briefing_notices(self, caller: Caller) -> list[str]:
        """One line for each of the caller's personal memories in their project that is popular and not yet named at
        this count of readers. Naming it is recorded, so the next briefing names it only once the count has grown by
        the re-prompt factor."""
        if caller.project is None:
            return []
        own = f"projects/{caller.project.project_id}/people/{caller.member_id}/"
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT r.path, COUNT(*) AS readers, p.readers AS prompted FROM memory_readers r"
                " LEFT JOIN popular_prompts p ON p.team = r.team AND p.path = r.path"
                " WHERE r.team = %s AND starts_with(r.path, %s) AND r.member_id <> %s AND r.read_at >= %s"
                " GROUP BY r.path, p.readers HAVING COUNT(*) >= %s ORDER BY r.path",
                (caller.team, own, caller.member_id, self._clock() - self._window, self._settings.popular_members),
            ).fetchall()
        due = [
            (row["path"], row["readers"])
            for row in rows
            if row["prompted"] is None or row["readers"] >= row["prompted"] * self._settings.popular_reprompt_factor
        ]
        named: list[tuple[str, int, Memory]] = []
        for path, readers in due:
            try:
                memory = self._store.read(caller.team, PurePosixPath(path))
            except Refused:
                continue
            if memory.status == "active":
                named.append((path, readers, memory))
        in_doubt = self._challenges.in_doubt(caller.team, [path for path, _, _ in named])
        named = [each for each in named if each[0] not in in_doubt]
        if not named:
            return []
        now = self._clock()
        with self._db.transaction() as conn:
            conn.cursor().executemany(
                "INSERT INTO popular_prompts (team, path, readers, prompted_at) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (team, path) DO UPDATE SET readers = EXCLUDED.readers, prompted_at = EXCLUDED.prompted_at",
                [(caller.team, path, readers, now) for path, readers, _ in named],
            )
        return [self._line(path, readers, memory) for path, readers, memory in named]

    def _line(self, path: str, readers: int, memory: Memory) -> str:
        days = max(1, round(self._settings.popular_window_days))
        return (
            f"[popular memory] Your personal memory {escape(memory.title)} ({path}) was read by {readers} other "
            f"members' sessions in the last {days} days. Suggest the member promote it to project or team memory "
            "with the promote tool, so the whole team gets it."
        )

    @contextmanager
    def on_change(
        self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> Iterator[None]:
        """A deleted memory forgets who read it and when its author was prompted."""
        gone = [str(path) for path in deletes]
        with self._db.transaction() as conn:
            if gone:
                conn.execute("DELETE FROM memory_readers WHERE team = %s AND path = ANY(%s)", (team, gone))
                conn.execute("DELETE FROM popular_prompts WHERE team = %s AND path = ANY(%s)", (team, gone))
            yield
