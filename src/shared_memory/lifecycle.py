"""How memory changes level: promoting, superseding, exceptions, challenges and retiring."""

from __future__ import annotations

import secrets
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
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
"""

RESOLUTIONS = ("supersede", "keep_both", "cancel")


class Lifecycle:
    def __init__(self, settings: Settings, db: Database, store: MemoryStore, index: SearchIndex, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._index = index
        self._clock = clock
        with db.transaction() as conn:
            conn.execute(SCHEMA)

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
        if location.member_id != caller.member.member_id:
            raise Refused("You can only promote your own personal memory.")
        if location.project_id != project.project_id:
            raise Refused("This memory belongs to another project. Promote it from a session in that project.")
        target: Level = "team" if level == "team" else "project"

        if reference is None:
            similar = self._index.similar(
                caller.team, location.path, project_id=project.project_id, threshold=self._settings.similar_threshold
            )
            if not similar:
                return self._move(caller, location, memory, target)
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
                raise Refused(
                    f"{similar_path} belongs to another author ({other.author}). Superseding another author's "
                    "memory needs a challenge, which is not available yet. Use keep_both or cancel."
                )
        self._forget(reference)
        return self._move(caller, location, memory, target, supersede=supersede, exception_to=exception_to)

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
    ) -> dict[str, Any]:
        folder = level_folder(target, memory.type, location.project_id)
        if location.topic:
            folder = folder / location.topic
        with self._store.change(caller.team, committer(caller), f"Promote: {memory.title}") as change:
            new_path = change.new_path(folder, location.path.stem)
            change.delete(location.path)
            change.write(new_path, replace(memory, replaces=supersede, exception_to=exception_to))
            if supersede is not None:
                old = PurePosixPath(supersede)
                change.write(old, replace(self._store.read(caller.team, old), status="superseded", superseded_by=str(new_path)))
        return {"status": "promoted", "path": str(new_path)}
