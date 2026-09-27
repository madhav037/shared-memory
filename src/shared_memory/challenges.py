"""Challenges and news: who may decide a challenge, and what sessions are told about them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from shared_memory.audit import CHALLENGE_RAISED, Audit
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity
from shared_memory.memory import locate
from shared_memory.store import MemoryStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS challenges (
    id BIGSERIAL PRIMARY KEY,
    team TEXT NOT NULL,
    kind TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_author TEXT NOT NULL,
    challenger_path TEXT,
    level TEXT NOT NULL,
    raised_by TEXT NOT NULL,
    promoted_by TEXT,
    raised_at TIMESTAMPTZ NOT NULL,
    author_notified_at TIMESTAMPTZ,
    state TEXT NOT NULL,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    explanation TEXT,
    reasoning TEXT
);
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS promoted_by TEXT;
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS reasoning TEXT;

CREATE TABLE IF NOT EXISTS notices (
    id BIGSERIAL PRIMARY KEY,
    team TEXT NOT NULL,
    member_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ
);
"""


@dataclass(frozen=True)
class Challenge:
    id: int
    kind: str
    target_path: str
    target_author: str
    challenger_path: str | None
    level: str
    raised_by: str
    promoted_by: str | None
    raised_at: datetime
    reasoning: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Challenge:
        return cls(
            row["id"],
            row["kind"],
            row["target_path"],
            row["target_author"],
            row["challenger_path"],
            row["level"],
            row["raised_by"],
            row["promoted_by"],
            row["raised_at"],
            row["reasoning"],
        )


def project_of(challenge: Challenge) -> str | None:
    """The project a challenge is about: the challenging memory's, or the challenged one's. Team memory has none."""
    for path in (challenge.challenger_path, challenge.target_path):
        if path is None:
            continue
        try:
            return locate(path).project_id
        except Refused:
            continue
    return None


class Challenges:
    def __init__(
        self, settings: Settings, db: Database, store: MemoryStore, identity: Identity, audit: Audit, clock: Clock
    ) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._identity = identity
        self._audit = audit
        self._clock = clock
        with db.transaction() as conn:
            conn.execute(SCHEMA)

    # Storing challenges

    def raise_challenge(
        self,
        caller: Caller,
        kind: str,
        target_path: str,
        target_author: str,
        challenger_path: str | None,
        level: str,
        promoted_by: str | None = None,
        reasoning: str | None = None,
    ) -> int:
        with self._db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO challenges (team, kind, target_path, target_author, challenger_path, level, raised_by,"
                " promoted_by, raised_at, state, reasoning) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s)"
                " RETURNING id",
                (
                    caller.team, kind, target_path, target_author, challenger_path, level, caller.member_id,
                    promoted_by, self._clock(), reasoning,
                ),  # fmt: skip
            ).fetchone()
        assert row is not None
        challenge_id: int = row["id"]
        self._audit.memory(
            caller, CHALLENGE_RAISED, target_path, challenge_id=challenge_id, challenge=kind, author=target_author
        )
        return challenge_id

    def open_challenge(self, team: str, challenge_id: int) -> Challenge | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM challenges WHERE id = %s AND team = %s AND state = 'open'", (challenge_id, team)
            ).fetchone()
        return None if row is None else Challenge.from_row(row)

    def open_challenges(
        self, team: str, *, target_path: str | None = None, challenger_paths: Iterable[str] | None = None
    ) -> list[Challenge]:
        conditions: list[str] = ["team = %s", "state = 'open'"]
        params: list[Any] = [team]
        if target_path is not None:
            conditions.append("target_path = %s")
            params.append(target_path)
        if challenger_paths is not None:
            conditions.append("challenger_path = ANY(%s)")
            params.append(list(challenger_paths))
        with self._db.transaction() as conn:
            rows = conn.execute(
                f"SELECT * FROM challenges WHERE {' AND '.join(conditions)} ORDER BY target_path, id", params
            ).fetchall()
        return [Challenge.from_row(row) for row in rows]

    def decide(self, challenge: Challenge, state: str, decider: str, explanation: str | None = None) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE challenges SET state = %s, decided_by = %s, decided_at = %s, explanation = %s WHERE id = %s",
                (state, decider, self._clock(), explanation, challenge.id),
            )

    def close_all_against(self, team: str, target_path: str, decider: str, explanation: str) -> None:
        """Close every open challenge against a memory, telling each member who raised one why."""
        for challenge in self.open_challenges(team, target_path=target_path):
            self.decide(challenge, "closed", decider, explanation)
            self.tell(team, challenge.raised_by, f"Your challenge {challenge.id} against {target_path} was closed: {explanation}")

    def tell(self, team: str, member_id: str, text: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO notices (team, member_id, text, created_at) VALUES (%s, %s, %s, %s)",
                (team, member_id, text, self._clock()),
            )

    def pending(self, team: str, paths: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        """For each personal memory path, the open challenges it is waiting on."""
        wanted = list(paths)
        labels: dict[str, list[dict[str, Any]]] = {path: [] for path in wanted}
        for challenge in self.open_challenges(team, challenger_paths=wanted):
            assert challenge.challenger_path is not None
            labels[challenge.challenger_path].append(
                {"challenge_id": challenge.id, "kind": challenge.kind, "replaces": challenge.target_path}
            )
        return labels

    def against(self, caller: Caller, path: str) -> list[dict[str, Any]]:
        """Every open challenge against one memory, and whether this member is the one who may decide it."""
        return [
            {
                "challenge_id": c.id,
                "kind": c.kind,
                "raised_by": c.raised_by,
                "challenger_path": c.challenger_path,
                "may_decide": self.may_decide(caller, c),
            }
            for c in self.open_challenges(caller.team, target_path=path)
        ]

    def waiting_for(self, caller: Caller) -> list[Challenge]:
        """Every open challenge this member may decide, in the projects they can reach."""
        reachable = {project.project_id for project in self._identity.projects(caller.member)} | {None}
        return [
            challenge
            for challenge in self.open_challenges(caller.team)
            if self.may_decide(caller, challenge) and project_of(challenge) in reachable
        ]

    def raised_by(self, caller: Caller) -> list[dict[str, Any]]:
        """Every challenge this member raised, newest first, and how each one ended."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, kind, target_path, challenger_path, raised_at, state, decided_by, decided_at, explanation,"
                " reasoning FROM challenges WHERE team = %s AND raised_by = %s ORDER BY id DESC",
                (caller.team, caller.member_id),
            ).fetchall()
        return [
            {
                "challenge_id": row["id"],
                "kind": row["kind"],
                "target_path": row["target_path"],
                "challenger_path": row["challenger_path"],
                "raised_at": row["raised_at"],
                "state": row["state"],
                "decided_by": row["decided_by"],
                "decided_at": row["decided_at"],
                "explanation": row["explanation"],
                "reasoning": row["reasoning"],
            }
            for row in rows
        ]

    # Who decides

    def may_decide(self, caller: Caller, challenge: Challenge) -> bool:
        """The author decides; after the fallback period, or once the author has left, any member may."""
        if challenge.target_author == caller.member_id:
            return True
        if self._clock() - challenge.raised_at >= timedelta(days=self._settings.challenge_fallback_days):
            return True
        return self._identity.is_removed(caller.team, challenge.target_author)

    def require_decider(self, caller: Caller, challenge: Challenge) -> None:
        if not self.may_decide(caller, challenge):
            raise Refused(
                f"Only {challenge.target_author}, the author of the challenged memory, can decide this challenge "
                f"until it has been open for {self._settings.challenge_fallback_days} days."
            )

    # What sessions are told

    def briefing_notices(self, caller: Caller) -> list[str]:
        """Every open challenge the member can decide, and news not yet delivered."""
        return [part for part in (self._render(caller, self.waiting_for(caller)), self._news(caller)) if part]

    def prompt_notices(self, caller: Caller) -> str | None:
        """Challenges against the member's memories not yet shown on a prompt (with the others against the same
        memory), and news not yet delivered."""
        mine = [c for c in self.open_challenges(caller.team) if c.target_author == caller.member_id]
        with self._db.transaction() as conn:
            fresh_targets = {
                row["target_path"]
                for row in conn.execute(
                    "SELECT target_path FROM challenges WHERE id = ANY(%s) AND author_notified_at IS NULL",
                    ([c.id for c in mine],),
                )
            }
            shown = [c for c in mine if c.target_path in fresh_targets]
            if shown:
                conn.execute(
                    "UPDATE challenges SET author_notified_at = %s WHERE id = ANY(%s)", (self._clock(), [c.id for c in shown])
                )
        text = "\n\n".join(part for part in (self._render(caller, shown), self._news(caller)) if part)
        return f"<shared-memory-notices>\n{text}\n</shared-memory-notices>" if text else None

    def _render(self, caller: Caller, challenges: list[Challenge]) -> str | None:
        if not challenges:
            return None
        lines = ["[challenges waiting for your decision]"]
        for target_path in dict.fromkeys(c.target_path for c in challenges):
            lines.append(f"{self._title(caller.team, target_path)} ({target_path}):")
            for c in (c for c in challenges if c.target_path == target_path):
                if c.challenger_path is None:
                    line = f"- Challenge {c.id} by {c.raised_by}: retire it"
                    line += f" — reasoning: {c.reasoning}" if c.reasoning else "."
                else:
                    try:
                        challenger = self._store.read(caller.team, PurePosixPath(c.challenger_path))
                        replacement = f'"{challenger.title}" ({c.challenger_path}): {challenger.summary}'
                    except Refused:
                        replacement = c.challenger_path
                    line = f"- Challenge {c.id} by {c.raised_by}: supersede it with {replacement}"
                    if c.reasoning:
                        line += f" — reasoning: {c.reasoning}"
                lines.append(line)
        lines.append(
            "Show these to the member and record their decision with decide_challenge (accept or reject). "
            "At most one challenge per memory can be accepted."
        )
        return "\n".join(lines)

    def _title(self, team: str, path: str) -> str:
        try:
            return self._store.read(team, PurePosixPath(path)).title
        except Refused:
            return path

    def _news(self, caller: Caller) -> str | None:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "UPDATE notices SET delivered_at = %s WHERE team = %s AND member_id = %s AND delivered_at IS NULL"
                " RETURNING id, text",
                (self._clock(), caller.team, caller.member_id),
            ).fetchall()
        texts = [row["text"] for row in sorted(rows, key=lambda row: row["id"])]
        return "[shared memory news]\n" + "\n".join(f"- {text}" for text in texts) if texts else None
