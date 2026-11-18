"""How often a project's sessions edit each of its files, for project health's coverage gaps (spec #504).

The before-edit hook counts each edit that goes ahead, once for each file it changes, in `file_edits`: one row per
project, repository, file and day, which only this module reads. A blocked edit changes nothing and isn't counted.
Counting is one statement, which also drops the counted files' own rows from before `KEPT_DAYS`, so the table keeps
only what a count can still ask for.

The interface:

- `count(session, paths)`: an edit that went ahead changed these files, each a path from the session's repository's
  root. A file outside the repository, or a session with no repository, counts nothing.
- `most_edited(project_id, days)`: the project's files edited in the last `days` days, the most edited first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from shared_memory.clock import Clock
from shared_memory.db import Database
from shared_memory.locks import OutsideRepository, from_root
from shared_memory.sessions import Session

# The longest window a count asks about, project health's: rows older than this are dropped as their file is edited.
KEPT_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_edits (
    project_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    -- From the repository's root, with forward slashes, as a lock keeps it.
    path TEXT NOT NULL,
    -- The server's day, in UTC.
    day DATE NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (project_id, repository, path, day)
);
"""

_COUNT = (
    "WITH gone AS (DELETE FROM file_edits WHERE project_id = %(project)s AND repository = %(repository)s"
    " AND path = ANY(%(paths)s) AND day < %(oldest)s)"
    " INSERT INTO file_edits (project_id, repository, path, day, count)"
    " SELECT %(project)s, %(repository)s, edited, %(day)s, 1 FROM unnest(%(paths)s::text[]) AS edited"
    " ON CONFLICT (project_id, repository, path, day) DO UPDATE SET count = file_edits.count + 1"
)


@dataclass(frozen=True)
class EditedFile:
    """A file in one of a project's repositories, and how many edits changed it."""

    repository: str
    path: str
    edits: int


class FileEdits:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def _today(self) -> date:
        return self._clock().date()

    def count(self, session: Session, paths: Sequence[str]) -> None:
        """An edit that went ahead in this session changed these files: count one edit of each, today."""
        if session.repository is None:
            return
        kept = []
        for path in paths:
            try:
                kept.append(from_root(path))
            except OutsideRepository:
                continue
        kept = list(dict.fromkeys(kept))
        if not kept:
            return
        today = self._today()
        with self._db.transaction() as conn:
            conn.execute(
                _COUNT,
                {
                    "project": session.project_id,
                    "repository": session.repository,
                    "paths": kept,
                    "day": today,
                    "oldest": today - timedelta(days=KEPT_DAYS),
                },
            )

    def most_edited(self, project_id: str, days: int) -> list[EditedFile]:
        """The project's files edited in the last `days` days, today among them, the most edited first and then by
        repository and path."""
        since = self._today() - timedelta(days=days - 1)
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT repository, path, SUM(count) AS edits FROM file_edits WHERE project_id = %s AND day >= %s"
                " GROUP BY repository, path ORDER BY edits DESC, repository, path",
                (project_id, since),
            ).fetchall()
        return [EditedFile(str(row["repository"]), str(row["path"]), int(row["edits"])) for row in rows]
