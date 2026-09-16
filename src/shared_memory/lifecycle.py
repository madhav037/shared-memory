"""How memory changes level: promoting, superseding, exceptions, challenges and retiring."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller
from shared_memory.index import SearchIndex
from shared_memory.memory import Level, Location, Memory, level_folder, locate
from shared_memory.service import committer, describe
from shared_memory.store import MemoryStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS promotions (
    reference TEXT PRIMARY KEY,
    team TEXT NOT NULL,
    member_id TEXT NOT NULL,
    path TEXT NOT NULL,
    level TEXT NOT NULL,
    similar_paths TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS challenges (
    id BIGSERIAL PRIMARY KEY,
    team TEXT NOT NULL,
    kind TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_author TEXT NOT NULL,
    challenger_path TEXT,
    level TEXT NOT NULL,
    raised_by TEXT NOT NULL,
    raised_at TIMESTAMPTZ NOT NULL,
    author_notified_at TIMESTAMPTZ,
    state TEXT NOT NULL,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    explanation TEXT
);

CREATE TABLE IF NOT EXISTS notices (
    id BIGSERIAL PRIMARY KEY,
    team TEXT NOT NULL,
    member_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ
);
"""

RESOLUTIONS = ("supersede", "keep_both", "cancel")


@dataclass(frozen=True)
class Challenge:
    id: int
    kind: str
    target_path: str
    target_author: str
    challenger_path: str | None
    level: str
    raised_by: str
    raised_at: datetime

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
            row["raised_at"],
        )


class Lifecycle:
    def __init__(self, settings: Settings, db: Database, store: MemoryStore, index: SearchIndex, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._index = index
        self._clock = clock
        with db.transaction() as conn:
            conn.execute(SCHEMA)

    # Promoting

    def promote(
        self,
        caller: Caller,
        path: str,
        level: str,
        reference: str | None = None,
        resolutions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        project = caller.require_project()
        if level not in ("project", "team"):
            raise Refused(f"Promote into 'project' or 'team' memory, not {level!r}.")
        location = locate(path)
        memory = self._store.read(caller.team, location.path)
        if location.level != "personal":
            raise Refused(f"This is already {location.level} memory. Only personal memory can be promoted.")
        promoted_by: str | None = None
        if location.member_id != caller.member.member_id:
            if location.member_id is None or not self._is_removed(caller.team, location.member_id):
                raise Refused(
                    "You can only promote your own personal memory, or the personal memory of a member who has "
                    "been removed from the team."
                )
            promoted_by = caller.member.member_id
        if location.project_id != project.project_id:
            raise Refused("This memory belongs to another project. Promote it from a session in that project.")
        pending = self._open_challenges(caller.team, challenger_path=str(location.path))
        if pending:
            raise Refused(f"This memory is waiting on challenge {pending[0].id}. Wait for it to be decided.")
        target: Level = "team" if level == "team" else "project"

        if reference is None:
            similar = self._index.similar(
                caller.team, location.path, project_id=project.project_id, threshold=self._settings.similar_threshold
            )
            if not similar:
                return self._move(caller, location, memory, target, promoted_by=promoted_by)
            reference = secrets.token_urlsafe(12)
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO promotions (reference, team, member_id, path, level, similar_paths, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (reference, caller.team, caller.member.member_id, path, level, [p for p, _ in similar], self._clock()),
                )
            return {
                "status": "similar_memories",
                "reference": reference,
                "similar": [
                    {**describe(PurePosixPath(p), self._store.read(caller.team, PurePosixPath(p))), "similarity": round(s, 3)}
                    for p, s in similar
                ],
                "next": "Judge whether each similar memory contradicts this one, ask the member, then call promote "
                "again with this reference and a resolution (supersede, keep_both or cancel) for every similar memory.",
            }

        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT similar_paths FROM promotions WHERE reference = %s AND team = %s AND member_id = %s"
                " AND path = %s AND level = %s",
                (reference, caller.team, caller.member.member_id, path, level),
            ).fetchone()
        if row is None:
            raise Refused("Unknown promotion reference for this memory. Call promote again without a reference.")
        chosen = dict(resolutions or {})
        if set(chosen) != set(row["similar_paths"]):
            raise Refused(
                "Give a resolution for every similar memory (supersede, keep_both or cancel): "
                + ", ".join(row["similar_paths"])
            )
        unknown = sorted({value for value in chosen.values() if value not in RESOLUTIONS})
        if unknown:
            raise Refused(f"Unknown resolution {unknown[0]!r}: use supersede, keep_both or cancel.")
        if "cancel" in chosen.values():
            self._forget(reference)
            return {"status": "cancelled", "path": path}
        supersede: str | None = None
        exception_to: str | None = None
        challenged: tuple[str, Memory] | None = None
        for similar_path in sorted(p for p, resolution in chosen.items() if resolution == "supersede"):
            similar_location = locate(similar_path)
            other = self._store.read(caller.team, similar_location.path)
            if other.status != "active":
                raise Refused(f"{similar_path} is no longer active. Call promote again without a reference.")
            if target == "project" and similar_location.level == "team":
                if exception_to is not None:
                    raise Refused("A project memory can be an exception to only one team memory.")
                exception_to = similar_path
            elif other.author == caller.member.member_id:
                if supersede is not None:
                    raise Refused("A promotion can supersede only one memory. Retire the others first.")
                supersede = similar_path
            else:
                if challenged is not None:
                    raise Refused("A promotion can challenge only one memory at a time.")
                challenged = (similar_path, other)
        if challenged is not None and (supersede is not None or exception_to is not None):
            raise Refused(
                "A promotion that challenges another author's memory can't also supersede or be an exception. "
                "Challenge first; once it's accepted, promote the rest."
            )
        self._forget(reference)
        if challenged is not None:
            return self._raise(caller, "supersede", challenged[0], challenged[1], str(location.path), target)
        return self._move(
            caller, location, memory, target, supersede=supersede, exception_to=exception_to, promoted_by=promoted_by
        )

    def _forget(self, reference: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM promotions WHERE reference = %s", (reference,))

    def _move(
        self,
        caller: Caller,
        location: Location,
        memory: Memory,
        target: Level,
        *,
        supersede: str | None = None,
        exception_to: str | None = None,
        promoted_by: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        folder = level_folder(target, memory.type, location.project_id)
        if location.topic:
            folder = folder / location.topic
        with self._store.change(caller.team, committer(caller), message or f"Promote: {memory.title}") as change:
            new_path = change.new_path(folder, location.path.stem)
            change.delete(location.path)
            change.write(
                new_path,
                replace(memory, replaces=supersede, exception_to=exception_to, promoted_by=promoted_by or memory.promoted_by),
            )
            if supersede is not None:
                old = PurePosixPath(supersede)
                change.write(old, replace(self._store.read(caller.team, old), status="superseded", superseded_by=str(new_path)))
        return {"status": "promoted", "path": str(new_path)}

    # Retiring

    def retire(self, caller: Caller, path: str) -> dict[str, Any]:
        location = locate(path)
        memory = self._store.read(caller.team, location.path)
        if location.level == "personal":
            raise Refused("Personal memory isn't retired. If it's yours and no longer true, remove it with delete_memory.")
        if memory.status != "active":
            raise Refused(f"This memory is already {memory.status}.")
        if memory.author != caller.member.member_id:
            return self._raise(caller, "retire", str(location.path), memory, None, location.level)
        with self._store.change(caller.team, committer(caller), f"Retire: {memory.title}") as change:
            change.write(location.path, replace(memory, status="retired"))
        return {"status": "retired", "path": str(location.path)}

    # Challenges

    def _raise(
        self, caller: Caller, kind: str, target_path: str, target: Memory, challenger_path: str | None, level: str
    ) -> dict[str, Any]:
        with self._db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO challenges (team, kind, target_path, target_author, challenger_path, level, raised_by,"
                " raised_at, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open') RETURNING id",
                (caller.team, kind, target_path, target.author, challenger_path, level, caller.member.member_id, self._clock()),
            ).fetchone()
        assert row is not None
        return {
            "status": "challenge_raised",
            "challenge_id": row["id"],
            "challenges": target_path,
            "author": target.author,
            "next": f"{target.author} decides. Until then the challenged memory stays active.",
        }

    def _open_challenges(
        self, team: str, *, target_path: str | None = None, challenger_path: str | None = None
    ) -> list[Challenge]:
        conditions, params = ["team = %s", "state = 'open'"], [team]
        if target_path is not None:
            conditions.append("target_path = %s")
            params.append(target_path)
        if challenger_path is not None:
            conditions.append("challenger_path = %s")
            params.append(challenger_path)
        with self._db.transaction() as conn:
            rows = conn.execute(
                f"SELECT * FROM challenges WHERE {' AND '.join(conditions)} ORDER BY id", params
            ).fetchall()
        return [Challenge.from_row(row) for row in rows]

    def challenge_info(self, team: str, path: str) -> dict[str, Any]:
        """What a read of this memory should show about challenges: pending as challenger, open as target."""
        return {
            "pending": [
                {"challenge_id": c.id, "kind": c.kind, "replaces": c.target_path}
                for c in self._open_challenges(team, challenger_path=path)
            ],
            "open_challenges": [
                {"challenge_id": c.id, "kind": c.kind, "raised_by": c.raised_by, "challenger_path": c.challenger_path}
                for c in self._open_challenges(team, target_path=path)
            ],
        }

    def _is_removed(self, team: str, member_id: str) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.removed_at FROM members m JOIN teams t ON t.id = m.team_id WHERE t.code = %s AND m.member_id = %s",
                (team, member_id),
            ).fetchone()
        return row is not None and row["removed_at"] is not None

    def _may_decide(self, caller: Caller, challenge: Challenge) -> bool:
        """The author decides; after the fallback period, or once the author has left, any member may."""
        if challenge.target_author == caller.member.member_id:
            return True
        if self._clock() - challenge.raised_at >= timedelta(days=self._settings.challenge_fallback_days):
            return True
        return self._is_removed(caller.team, challenge.target_author)

    def decide_challenge(self, caller: Caller, challenge_id: int, decision: str) -> dict[str, Any]:
        if decision not in ("accept", "reject"):
            raise Refused("Decide a challenge with 'accept' or 'reject'.")
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM challenges WHERE id = %s AND team = %s AND state = 'open'", (challenge_id, caller.team)
            ).fetchone()
        if row is None:
            raise Refused(f"There is no open challenge {challenge_id} in your team.")
        challenge = Challenge.from_row(row)
        if not self._may_decide(caller, challenge):
            raise Refused(
                f"Only {challenge.target_author}, the author of the challenged memory, can decide this challenge "
                f"until it has been open for {self._settings.challenge_fallback_days} days."
            )
        target_path = PurePosixPath(challenge.target_path)
        target = self._store.read(caller.team, target_path)
        now = self._clock()
        decider = caller.member.member_id

        if decision == "reject":
            with self._db.transaction() as conn:
                self._close(conn, challenge.id, "rejected", decider, now, None)
                self._notify(
                    conn, caller.team, challenge.raised_by,
                    f"Your challenge {challenge.id} against {challenge.target_path} was rejected by {decider}. "
                    "Your memory stays personal memory.",
                )
            return {"status": "rejected", "challenge_id": challenge.id}

        if target.status != "active":
            raise Refused(f"{challenge.target_path} is no longer active, so this challenge can't be accepted.")
        result: dict[str, Any]
        if challenge.kind == "supersede":
            assert challenge.challenger_path is not None
            challenger_location = locate(challenge.challenger_path)
            if not self._store.exists(caller.team, challenger_location.path):
                with self._db.transaction() as conn:
                    self._close(conn, challenge.id, "withdrawn", decider, now, "The challenging memory was deleted.")
                raise Refused("The challenging memory no longer exists, so the challenge has been withdrawn.")
            challenger = self._store.read(caller.team, challenger_location.path)
            level: Level = "team" if challenge.level == "team" else "project"
            moved = self._move(
                caller, challenger_location, challenger, level, supersede=challenge.target_path,
                message=f"Accept challenge {challenge.id}: {challenger.title}",
            )
            result = {"status": "accepted", "challenge_id": challenge.id, "path": moved["path"]}
            outcome = f"Your challenge {challenge.id} was accepted by {decider}: your memory is now {level} memory at {moved['path']}."
        else:
            with self._store.change(caller.team, committer(caller), f"Accept challenge {challenge.id}: retire {target.title}") as change:
                change.write(target_path, replace(target, status="retired"))
            result = {"status": "accepted", "challenge_id": challenge.id, "retired": challenge.target_path}
            outcome = f"Your challenge {challenge.id} was accepted by {decider}: {challenge.target_path} is retired."

        with self._db.transaction() as conn:
            self._close(conn, challenge.id, "accepted", decider, now, None)
            self._notify(conn, caller.team, challenge.raised_by, outcome)
            for other in self._open_challenges(caller.team, target_path=challenge.target_path):
                explanation = f"Closed because challenge {challenge.id} by {challenge.raised_by} was accepted instead."
                self._close(conn, other.id, "closed", decider, now, explanation)
                self._notify(
                    conn, caller.team, other.raised_by,
                    f"Your challenge {other.id} against {other.target_path} was closed: {explanation}",
                )
        return result

    @staticmethod
    def _close(conn: Conn, challenge_id: int, state: str, decider: str, now: datetime, explanation: str | None) -> None:
        conn.execute(
            "UPDATE challenges SET state = %s, decided_by = %s, decided_at = %s, explanation = %s WHERE id = %s",
            (state, decider, now, explanation, challenge_id),
        )

    def _notify(self, conn: Conn, team: str, member_id: str, text: str) -> None:
        conn.execute(
            "INSERT INTO notices (team, member_id, text, created_at) VALUES (%s, %s, %s, %s)",
            (team, member_id, text, self._clock()),
        )

    # What sessions are told

    def _decidable(self, caller: Caller) -> list[Challenge]:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM challenges WHERE team = %s AND state = 'open' ORDER BY target_path, id", (caller.team,)
            ).fetchall()
        return [c for c in (Challenge.from_row(row) for row in rows) if self._may_decide(caller, c)]

    def _render_challenges(self, caller: Caller, challenges: list[Challenge]) -> str | None:
        if not challenges:
            return None
        lines = ["[challenges waiting for your decision]"]
        for target_path in dict.fromkeys(c.target_path for c in challenges):
            try:
                target_title = self._store.read(caller.team, PurePosixPath(target_path)).title
            except Refused:
                target_title = target_path
            lines.append(f"{target_title} ({target_path}):")
            for c in (c for c in challenges if c.target_path == target_path):
                if c.kind == "retire" or c.challenger_path is None:
                    lines.append(f"- Challenge {c.id} by {c.raised_by}: retire it.")
                    continue
                try:
                    challenger = self._store.read(caller.team, PurePosixPath(c.challenger_path))
                    what = f'"{challenger.title}" ({c.challenger_path}): {challenger.summary}'
                except Refused:
                    what = c.challenger_path
                lines.append(f"- Challenge {c.id} by {c.raised_by}: supersede it with {what}")
        lines.append(
            "Show these to the member and record their decision with decide_challenge (accept or reject). "
            "At most one challenge per memory can be accepted."
        )
        return "\n".join(lines)

    def _undelivered(self, caller: Caller) -> list[str]:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "UPDATE notices SET delivered_at = %s WHERE team = %s AND member_id = %s AND delivered_at IS NULL"
                " RETURNING id, text",
                (self._clock(), caller.team, caller.member.member_id),
            ).fetchall()
        return [row["text"] for row in sorted(rows, key=lambda row: row["id"])]

    def briefing_notices(self, caller: Caller) -> list[str]:
        """Every open challenge the member can decide, and news not yet delivered."""
        parts = [self._render_challenges(caller, self._decidable(caller)), *self._notice_lines(caller)]
        return [part for part in parts if part]

    def prompt_notices(self, caller: Caller) -> str | None:
        """Challenges the member hasn't been told about on a prompt yet, and news not yet delivered."""
        fresh = [
            c
            for c in self._decidable(caller)
            if c.target_author == caller.member.member_id and not self._author_notified(c.id)
        ]
        parts = [self._render_challenges(caller, fresh), *self._notice_lines(caller)]
        if fresh:
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE challenges SET author_notified_at = %s WHERE id = ANY(%s)", (self._clock(), [c.id for c in fresh])
                )
        text = "\n\n".join(part for part in parts if part)
        return f"<shared-memory-notices>\n{text}\n</shared-memory-notices>" if text else None

    def _author_notified(self, challenge_id: int) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute("SELECT author_notified_at FROM challenges WHERE id = %s", (challenge_id,)).fetchone()
        return row is not None and row["author_notified_at"] is not None

    def _notice_lines(self, caller: Caller) -> list[str]:
        texts = self._undelivered(caller)
        return ["[shared memory news]\n" + "\n".join(f"- {text}" for text in texts)] if texts else []
