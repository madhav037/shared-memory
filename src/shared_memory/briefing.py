"""Pins and the briefing every session receives when it starts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller
from shared_memory.memory import FOLDER_TYPES, Memory, locate
from shared_memory.recall import FRAMING
from shared_memory.store import MemoryStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS pins (
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    project_id TEXT,
    pinned_by TEXT NOT NULL,
    pinned_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (team, path)
);
"""


ONLY_ACCEPTED = "Only project memory and team memory can be pinned, so the briefing holds accepted memory."


@dataclass(frozen=True)
class PinTarget:
    path: str
    kind: str
    level: str
    project_id: str | None


def _tokens(text: str) -> int:
    return (len(text) + 3) // 4


def pin_target(path: str) -> PinTarget:
    cleaned = path.replace("\\", "/").strip("/")
    if cleaned.endswith(".md"):
        location = locate(cleaned)
        if location.level == "personal":
            raise Refused(ONLY_ACCEPTED)
        return PinTarget(str(location.path), "memory", location.level, location.project_id)
    parts = PurePosixPath(cleaned).parts
    if ".." not in parts and len(parts) == 3 and parts[0] == "team" and parts[1] in FOLDER_TYPES:
        return PinTarget(cleaned, "topic", "team", None)
    if ".." not in parts and len(parts) == 5 and parts[0] == "projects" and parts[2] == "shared" and parts[3] in FOLDER_TYPES:
        return PinTarget(cleaned, "topic", "project", parts[1])
    if len(parts) >= 3 and parts[0] == "projects" and parts[2] == "people":
        raise Refused(ONLY_ACCEPTED)
    raise Refused(f"{path!r} is neither a project or team memory nor a topic folder.")


class Briefing:
    def __init__(self, settings: Settings, db: Database, store: MemoryStore, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._clock = clock
        with db.transaction() as conn:
            conn.execute(SCHEMA)

    def pin(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        target = pin_target(path)
        rendered = self._render(caller.team, target)
        if rendered is None:
            raise Refused(f"There is no active memory or topic at {target.path!r} to pin.")
        with self._db.transaction() as conn:
            if conn.execute("SELECT 1 FROM pins WHERE team = %s AND path = %s", (caller.team, target.path)).fetchone():
                raise Refused(f"{target.path} is already pinned.")
            if target.level == "team":
                projects = [row["project_id"] for row in conn.execute(
                    "SELECT DISTINCT project_id FROM pins WHERE team = %s AND level = 'project'", (caller.team,)
                )]
            else:
                projects = [target.project_id]
        cap = self._settings.briefing_cap_tokens
        for project_id in projects or [None]:
            pinned = self._pinned(caller.team, project_id)
            total = _tokens(FRAMING) + sum(tokens for _, tokens in pinned) + _tokens(rendered)
            if total > cap:
                listing = "; ".join(f"{pin_path} (about {tokens} tokens)" for pin_path, tokens in pinned) or "nothing"
                raise Refused(
                    f"Pinning this (about {_tokens(rendered)} tokens) would put the briefing over its cap of about "
                    f"{cap} tokens. Unpin something first. Pinned now: {listing}."
                )
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO pins (team, path, kind, level, project_id, pinned_by, pinned_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (caller.team, target.path, target.kind, target.level, target.project_id, caller.member_id, self._clock()),
            )
        return {"pinned": target.path}

    def unpin(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        cleaned = path.replace("\\", "/").strip("/")
        with self._db.transaction() as conn:
            deleted = conn.execute("DELETE FROM pins WHERE team = %s AND path = %s", (caller.team, cleaned)).rowcount
        if not deleted:
            raise Refused(f"{cleaned} is not pinned.")
        return {"unpinned": cleaned}

    def on_change(self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]) -> None:
        """Pins follow memory: a pin moves to whatever supersedes its memory and goes away when it is retired."""
        with self._db.transaction() as conn:
            for path, memory in writes.items():
                if memory.status == "superseded" and memory.superseded_by:
                    new = locate(memory.superseded_by)
                    conn.execute(
                        "UPDATE pins SET path = %s, level = %s, project_id = %s WHERE team = %s AND path = %s",
                        (str(new.path), new.level, new.project_id, team, str(path)),
                    )
                elif memory.status == "retired":
                    conn.execute("DELETE FROM pins WHERE team = %s AND path = %s", (team, str(path)))

    def for_session(self, caller: Caller, extra: list[str] | None = None) -> str | None:
        """The briefing: pinned memories for the session's project within the cap, plus any extra notices."""
        if caller.project is None:
            return None
        budget = self._settings.briefing_cap_tokens - _tokens(FRAMING)
        sections: list[str] = []
        left_out: list[str] = []
        for path, text in self._pinned_texts(caller.team, caller.project.project_id):
            if _tokens(text) <= budget:
                sections.append(text)
                budget -= _tokens(text)
            else:
                left_out.append(path)
        if left_out:
            sections.append(
                f"[briefing cap] These pins did not fit within the briefing cap and were left out: {', '.join(left_out)}. "
                "Suggest the member unpin something to make room."
            )
        sections.extend(extra or [])
        if not sections:
            return None
        return "<shared-memory-briefing>\n" + FRAMING + "\n\n" + "\n\n".join(sections) + "\n</shared-memory-briefing>"

    def _rows(self, team: str, project_id: str | None) -> list[PinTarget]:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT path, kind, level, project_id FROM pins WHERE team = %s"
                " AND (level = 'team' OR project_id = %s) ORDER BY pinned_at, path",
                (team, project_id),
            ).fetchall()
        return [PinTarget(row["path"], row["kind"], row["level"], row["project_id"]) for row in rows]

    def _pinned_texts(self, team: str, project_id: str | None) -> list[tuple[str, str]]:
        """(path, rendered text) for each pin visible from a project, oldest first."""
        texts = []
        for target in self._rows(team, project_id):
            rendered = self._render(team, target)
            if rendered is not None:
                texts.append((target.path, rendered))
        return texts

    def _pinned(self, team: str, project_id: str | None) -> list[tuple[str, int]]:
        """(path, approximate tokens) for each pin visible from a project."""
        return [(path, _tokens(text)) for path, text in self._pinned_texts(team, project_id)]

    def _render(self, team: str, target: PinTarget) -> str | None:
        if target.kind == "memory":
            try:
                memory = self._store.read(team, PurePosixPath(target.path))
            except Refused:
                return None
            if memory.status != "active":
                return None
            return f"[{target.level} memory] {memory.title} ({target.path})\n{memory.body}"
        memories, _ = self._store.list_folder(team, PurePosixPath(target.path))
        lines = [f"- {memory.title}: {memory.summary}" for _, memory in memories if memory.status == "active"]
        if not lines:
            return None
        name = PurePosixPath(target.path).name
        return f"[{target.level} memory topic] {name} ({target.path})\n" + "\n".join(lines)
