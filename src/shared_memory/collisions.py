"""Collision warnings: a session is told when another active session in its project is working on nearly the same thing.

Two activities are nearly the same when their embeddings, from the server's own model, are as similar as
`Settings.collision_threshold` or more. An activity shown from a card counts like a stated one. A prompt is compared
too: its embedding, which recall needs anyway, against every other session's activity, so a later session is warned on
its first prompt, before its agent has stated an activity. The prompt and its embedding are never kept. A session is
warned once per overlapping session, and again only when that session's activity has changed. A member's own two
sessions warn each other; sessions in two projects never do.

Everything is kept in Postgres, so every worker agrees (ADR-0013):

- `activity_embeddings`: the embedding of each session's activity, beside the text it was made from. It is written when
  the activity is stated, and filled in on a prompt for a line that has none yet or has changed, which is how a card's
  title gets one.
- `collision_warnings`: per session and other session, the other's activity the session was last warned about.
- `collisions`: one per pair of overlapping sessions, kept when it is first found: which is the later session (the one
  whose prompt or activity made it), which the earlier, the score and the cause (`prompt` or `activity`).

All three are cleared through `Sessions.on_gone` when either session ends or comes back from idle. Only this module reads
them.

What other modules stand on, all of it on `Collisions`:

- `embed(session, activity)`: keep the embedding of the activity a session has just stated.
- `prompt_embedding(caller, session, prompt)`: the prompt's embedding, made only when there is something to compare
  it with.
- `warnings(caller, session, prompt)`: what the session is told now, its prompt compared too when given. Asking marks
  it told and keeps each collision found.
- `of(session)`: the collisions a session is in, as the later session or the earlier.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pgvector import Vector

from shared_memory.activity import Activities, SessionActivity
from shared_memory.clock import Clock
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

CREATE TABLE IF NOT EXISTS collisions (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    -- The session whose prompt or activity made the collision.
    later_session_id BIGINT NOT NULL REFERENCES sessions(id),
    earlier_session_id BIGINT NOT NULL REFERENCES sessions(id),
    score DOUBLE PRECISION NOT NULL,
    cause TEXT NOT NULL CHECK (cause IN ('prompt', 'activity')),
    found_at TIMESTAMPTZ NOT NULL
);
-- One per pair, whichever way round: the first finding decides which session is later.
CREATE UNIQUE INDEX IF NOT EXISTS collisions_pair
    ON collisions (LEAST(later_session_id, earlier_session_id), GREATEST(later_session_id, earlier_session_id));
CREATE INDEX IF NOT EXISTS collisions_earlier ON collisions (earlier_session_id);
"""


class Cause(StrEnum):
    """What made a collision: the later session's prompt, or its activity."""

    PROMPT = "prompt"
    ACTIVITY = "activity"


@dataclass(frozen=True)
class Overlap:
    """Another active session whose activity is nearly the same as the asking session's."""

    session: Session
    activity: str
    score: float
    cause: Cause


@dataclass(frozen=True)
class Collision:
    """Two sessions found working on nearly the same thing, by their ids."""

    project_id: str
    later_session_id: int
    earlier_session_id: int
    score: float
    cause: Cause
    found_at: datetime


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
        self,
        settings: Settings,
        db: Database,
        sessions: Sessions,
        activities: Activities,
        embedder: Embedder,
        clock: Clock,
    ) -> None:
        self._threshold = settings.collision_threshold
        self._db = db
        self._clock = clock
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
        conn.execute(
            "DELETE FROM collisions WHERE later_session_id = ANY(%s) OR earlier_session_id = ANY(%s)", (gone, gone)
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

    def _working(self, session: Session) -> tuple[SessionActivity | None, list[SessionActivity]]:
        """This session's own activity, if it has one, and the other active sessions in its project that have one."""
        working = [each for each in self._activities.in_project(session.project_id) if each.activity]
        own = next((each for each in working if each.session.id == session.id), None)
        return own, [each for each in working if each.session.id != session.id]

    def prompt_embedding(self, caller: Caller, session: Session, prompt: str) -> list[float] | None:
        """The embedding of a prompt this session sent, to compare with the other sessions' activities. None when no
        other session in its project has an activity, so a prompt is embedded here only when there is something to
        compare it with. Not kept: recall asks for the same embedding next, and is answered from the query cache."""
        if not prompt.strip() or caller.project is None or caller.project.project_id in caller.unreachable:
            return None
        _, others = self._working(session)
        return self._embedder.query(prompt) if others else None

    def _overlapping(self, session: Session, prompt: list[float] | None) -> list[Overlap]:
        """The other active sessions in this session's project whose activity is nearly the same as its own activity
        or as its prompt, oldest first, each with the higher of the two scores. None for a session with neither."""
        own, others = self._working(session)
        if not others or (own is None and prompt is None):
            return []
        embeddings = self._embeddings([*([own] if own else []), *others])
        overlaps = []
        for each in others:
            theirs = embeddings[each.session.id]
            scores = [(similarity(prompt, theirs), Cause.PROMPT)] if prompt is not None else []
            if own is not None:
                scores.append((similarity(embeddings[session.id], theirs), Cause.ACTIVITY))
            score, cause = max(scores, key=lambda scored: scored[0])
            if score >= self._threshold:
                overlaps.append(Overlap(each.session, each.activity or "", score, cause))
        return overlaps

    def _keep_collisions(self, later: Session, overlaps: Sequence[Overlap]) -> None:
        """Keep each overlap as a collision with this session as the later one, unless the pair already has one."""
        now = self._clock()
        with self._db.transaction() as conn:
            for overlap in overlaps:
                conn.execute(
                    "INSERT INTO collisions (project_id, later_session_id, earlier_session_id, score, cause, found_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (later.project_id, later.id, overlap.session.id, overlap.score, overlap.cause.value, now),
                )

    def of(self, session: Session) -> list[Collision]:
        """The collisions this session is in, as the later session or the earlier, oldest first."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT project_id, later_session_id, earlier_session_id, score, cause, found_at FROM collisions"
                " WHERE later_session_id = %s OR earlier_session_id = %s ORDER BY found_at, id",
                (session.id, session.id),
            ).fetchall()
        return [
            Collision(
                row["project_id"],
                row["later_session_id"],
                row["earlier_session_id"],
                row["score"],
                Cause(row["cause"]),
                row["found_at"],
            )
            for row in rows
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

    def warnings(self, caller: Caller, session: Session, prompt: list[float] | None = None) -> list[str]:
        """What this session is told now about possible collisions, its prompt compared too when its embedding is
        given: one line per overlapping session it has not been warned about since that session's activity last
        changed. Asking marks them told, and keeps each collision found with this session as the later one unless the
        pair already has one. Nothing for a session in a project its member can't reach."""
        if caller.project is None or caller.project.project_id in caller.unreachable:
            return []
        overlaps = self._overlapping(session, prompt)
        if not overlaps:
            return []
        self._keep_collisions(session, overlaps)
        return [warning(session, overlap) for overlap in self._not_yet_told(session, overlaps)]
