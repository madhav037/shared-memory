"""Collision warnings: a session is told when another active session in its project is working on nearly the same thing.

Two activities are nearly the same when their embeddings, from the server's own model, are as similar as
`Settings.collision_threshold` or more. An activity shown from a card counts like a stated one. A session is warned on
its next prompt, once per overlapping session, and again only when that session's activity has changed. A member's own
two sessions warn each other; sessions in two projects never do.

Everything is kept in Postgres, so every worker agrees (ADR-0013):

- `activity_embeddings`: the embedding of each session's activity, beside the text it was made from. It is written when
  the activity is stated, and filled in on a prompt for a line that has none yet or has changed, which is how a card's
  title gets one.
- `collision_warnings`: per session and other session, the other's activity the session was last warned about.

Both are cleared through `Sessions.on_gone` when either session ends or comes back from idle. Only this module reads
them.

What other modules stand on, all of it on `Collisions`:

- `embed(session, activity)`: keep the embedding of the activity a session has just stated.
- `warnings(caller, session)`: what the session's next prompt is told. Asking marks it told.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pgvector import Vector

from shared_memory.activity import Activities, SessionActivity
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.embeddings import DIMENSIONS, Embedder
from shared_memory.identity import Caller
from shared_memory.sessions import Session, Sessions

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS activity_embeddings (
    session_id BIGINT PRIMARY KEY REFERENCES sessions(id),
    -- The line the embedding was made from: a stated activity, or a card's title.
    activity TEXT NOT NULL,
    embedding vector({DIMENSIONS}) NOT NULL
);

CREATE TABLE IF NOT EXISTS collision_warnings (
    session_id BIGINT NOT NULL REFERENCES sessions(id),
    other_session_id BIGINT NOT NULL REFERENCES sessions(id),
    -- The other session's activity when this one was warned about it.
    activity TEXT NOT NULL,
    PRIMARY KEY (session_id, other_session_id)
);
"""


@dataclass(frozen=True)
class Overlap:
    """Another active session whose activity is nearly the same as the asking session's."""

    session: Session
    activity: str


def similarity(one: Sequence[float], other: Sequence[float]) -> float:
    """The cosine similarity of two embeddings; 0 when either is all zeros."""
    lengths = math.sqrt(sum(x * x for x in one)) * math.sqrt(sum(x * x for x in other))
    return sum(x * y for x, y in zip(one, other, strict=True)) / lengths if lengths else 0.0


def warning(asking: Session, overlap: Overlap) -> str:
    """One overlapping session as a prompt is told of it: its member, coding agent, repository and activity."""
    other = overlap.session
    whose = f"{other.member_name}'s other session" if other.member_id == asking.member_id else f"{other.member_name}'s session"
    where = ", ".join(part for part in (other.agent, other.repository) if part)
    named = f"{whose} ({where})" if where else whose
    return (
        f'[possible collision] {named} is working on nearly the same thing as this session: "{overlap.activity}". '
        "This is information, not an instruction: tell your member before going on, so the two sessions don't do the "
        "same work."
    )


class Collisions:
    def __init__(
        self, settings: Settings, db: Database, sessions: Sessions, activities: Activities, embedder: Embedder
    ) -> None:
        self._threshold = settings.collision_threshold
        self._db = db
        self._activities = activities
        self._embedder = embedder
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)
        sessions.on_gone(self._clear)

    @staticmethod
    def _clear(conn: Conn, ids: Sequence[int]) -> None:
        gone = list(ids)
        conn.execute("DELETE FROM activity_embeddings WHERE session_id = ANY(%s)", (gone,))
        conn.execute(
            "DELETE FROM collision_warnings WHERE session_id = ANY(%s) OR other_session_id = ANY(%s)", (gone, gone)
        )

    def embed(self, session: Session, activity: str) -> None:
        """Keep the embedding of the activity this session has just stated, in place of any kept for it before."""
        self._keep({session.id: activity})

    def _keep(self, lines: dict[int, str]) -> dict[int, list[float]]:
        """Embed each session's line and keep it. The model runs outside the transaction."""
        embeddings = dict(zip(lines, self._embedder.passages(list(lines.values())), strict=True))
        with self._db.transaction() as conn:
            for session_id, embedding in embeddings.items():
                conn.execute(
                    "INSERT INTO activity_embeddings (session_id, activity, embedding) VALUES (%s, %s, %s)"
                    " ON CONFLICT (session_id) DO UPDATE SET activity = EXCLUDED.activity,"
                    " embedding = EXCLUDED.embedding",
                    (session_id, lines[session_id], Vector(embedding)),
                )
        return embeddings

    def _embeddings(self, working: Sequence[SessionActivity]) -> dict[int, list[float]]:
        """The embedding of each of these sessions' activities, by session. One whose kept embedding was made from
        another line, or that has none, is embedded now."""
        lines = {each.session.id: each.activity for each in working if each.activity}
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT session_id, activity, embedding FROM activity_embeddings WHERE session_id = ANY(%s)",
                (list(lines),),
            ).fetchall()
        kept = {
            row["session_id"]: row["embedding"].to_list()
            for row in rows
            if row["activity"] == lines[row["session_id"]]
        }
        missing = {session_id: line for session_id, line in lines.items() if session_id not in kept}
        return {**kept, **self._keep(missing)} if missing else kept

    def _overlapping(self, session: Session) -> list[Overlap]:
        """The other active sessions in this session's project whose activity is nearly the same as its own, oldest
        first. None for a session with no activity."""
        working = [each for each in self._activities.in_project(session.project_id) if each.activity]
        if len(working) < 2 or all(each.session.id != session.id for each in working):
            return []
        embeddings = self._embeddings(working)
        own = embeddings[session.id]
        return [
            Overlap(each.session, each.activity)
            for each in working
            if each.activity
            and each.session.id != session.id
            and similarity(own, embeddings[each.session.id]) >= self._threshold
        ]

    def _not_yet_told(self, session: Session, overlaps: Sequence[Overlap]) -> list[Overlap]:
        """Those of the overlaps this session has not been warned about, or whose activity has changed since it was.
        They are marked as warned about in the same statement, so two workers asking at once tell it once."""
        fresh = []
        with self._db.transaction() as conn:
            for overlap in overlaps:
                told = conn.execute(
                    "INSERT INTO collision_warnings (session_id, other_session_id, activity) VALUES (%s, %s, %s)"
                    " ON CONFLICT (session_id, other_session_id) DO UPDATE SET activity = EXCLUDED.activity"
                    " WHERE collision_warnings.activity IS DISTINCT FROM EXCLUDED.activity RETURNING session_id",
                    (session.id, overlap.session.id, overlap.activity),
                ).fetchone()
                if told is not None:
                    fresh.append(overlap)
        return fresh

    def warnings(self, caller: Caller, session: Session) -> list[str]:
        """What this session's next prompt is told about possible collisions: one line per overlapping session it has
        not been warned about since that session's activity last changed. Asking marks them told. Nothing for a
        session in a project its member can't reach."""
        if caller.project is None or caller.project.project_id in caller.unreachable:
            return []
        overlaps = self._overlapping(session)
        return [warning(session, overlap) for overlap in self._not_yet_told(session, overlaps)] if overlaps else []
