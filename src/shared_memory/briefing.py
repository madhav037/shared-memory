"""Pins and the briefing every session receives when it starts."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from shared_memory.audit import MEMORY_PINNED, MEMORY_UNPINNED, Audit
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


@dataclass(frozen=True)
class Work:
    """What the board adds to a member's briefing, one short line each: their cards overdue or due today, their other
    cards in Doing and Blocked, and the titles of their project's active known issues."""

    due: list[str] = field(default_factory=list)
    working: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)


# Room kept within the cap for the line counting the work that didn't fit.
COUNTS_TOKENS = 50


def _tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _work_sections(work: Work, budget: int) -> list[str]:
    """The member's work, part by part in order, each line only while it fits in the budget. Once a line doesn't fit,
    it and every line after it are counted instead."""
    parts = [
        ("[your cards] Overdue or due today:", work.due, True),
        ("[your cards] In Doing and Blocked:", work.working, True),
        (
            "[known issues] Broken in this project now; search memory for a workaround:",
            [f"- {title}" for title in work.known_issues],
            False,
        ),
    ]
    budget -= COUNTS_TOKENS
    sections: list[str] = []
    cards_left = known_issues_left = 0
    full = False
    for heading, lines, cards in parts:
        shown: list[str] = []
        for line in lines:
            cost = _tokens(line) + 1 + (0 if shown else _tokens(heading) + 1)
            if not full and cost <= budget:
                shown.append(line)
                budget -= cost
                continue
            full = True
            if cards:
                cards_left += 1
            else:
                known_issues_left += 1
        if shown:
            sections.append("\n".join([heading, *shown]))
    counted = []
    if cards_left:
        counted.append(f"{cards_left} more of your cards")
    if known_issues_left:
        counted.append(f"{known_issues_left} more known issue{'' if known_issues_left == 1 else 's'}")
    if counted:
        sections.append(
            f"[briefing cap] {' and '.join(counted)} did not fit within the briefing cap: the board tool lists your "
            "cards, and search finds the known issues."
        )
    return sections


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
    def __init__(self, settings: Settings, db: Database, store: MemoryStore, audit: Audit, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._audit = audit
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def pin(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        target = pin_target(path)
        caller.require_reach(target.path)
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
        self._audit.memory(caller, MEMORY_PINNED, target.path, pinned=target.kind, level=target.level)
        return {"pinned": target.path}

    def unpin(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        cleaned = path.replace("\\", "/").strip("/")
        caller.require_reach(cleaned)
        with self._db.transaction() as conn:
            deleted = conn.execute("DELETE FROM pins WHERE team = %s AND path = %s", (caller.team, cleaned)).rowcount
        if not deleted:
            raise Refused(f"{cleaned} is not pinned.")
        self._audit.memory(caller, MEMORY_UNPINNED, cleaned)
        return {"unpinned": cleaned}

    def pinned_paths(self, team: str) -> set[str]:
        """Every path this team has pinned, for marking up what the console shows."""
        with self._db.transaction() as conn:
            rows = conn.execute("SELECT path FROM pins WHERE team = %s", (team,)).fetchall()
        return {row["path"] for row in rows}

    def listed(self, caller: Caller) -> list[dict[str, Any]]:
        """Everything pinned that this project's sessions are briefed with, oldest pin first."""
        project = caller.require_project()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT path, kind, level, project_id, pinned_by, pinned_at FROM pins WHERE team = %s"
                " AND (level = 'team' OR project_id = %s) ORDER BY pinned_at, path",
                (caller.team, project.project_id),
            ).fetchall()
        pins = []
        for row in rows:
            target = PinTarget(row["path"], row["kind"], row["level"], row["project_id"])
            rendered = self._render(caller.team, target)
            pins.append(
                {
                    "path": target.path,
                    "kind": target.kind,
                    "level": target.level,
                    "title": self._name(caller.team, target),
                    "tokens": _tokens(rendered) if rendered else 0,
                    "pinned_by": row["pinned_by"],
                    "pinned_at": row["pinned_at"],
                }
            )
        return pins

    def _name(self, team: str, target: PinTarget) -> str:
        """What to call a pin: the memory's title, or the topic folder's name."""
        if target.kind == "memory":
            try:
                return self._store.read(team, PurePosixPath(target.path)).title
            except Refused:
                return PurePosixPath(target.path).stem
        return PurePosixPath(target.path).name

    @contextmanager
    def on_change(
        self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> Iterator[None]:
        """Pins follow memory: a pin moves to whatever supersedes its memory and goes away when it is retired.

        They follow in one transaction, which commits only once the save has landed everywhere else."""
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
            yield

    def for_session(
        self, caller: Caller, extra: list[str] | None = None, work: Work | None = None, followed_by: str | None = None
    ) -> str | None:
        """The briefing: pinned memories for the session's project within the cap, any extra notices, then the member's
        work from the board in what is left of the cap, with counts of what didn't fit. What the session is told right
        after its briefing (followed_by) is not in it, but takes its room out of what is left for the work."""
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
        notes = list(extra or [])
        if left_out:
            notes.insert(
                0,
                f"[briefing cap] These pins did not fit within the briefing cap and were left out: {', '.join(left_out)}. "
                "Suggest the member unpin something to make room.",
            )
        sections.extend(notes)
        budget -= sum(_tokens(note) for note in notes)
        if followed_by:
            budget -= _tokens(followed_by) + 1
        sections.extend(_work_sections(work or Work(), budget))
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
