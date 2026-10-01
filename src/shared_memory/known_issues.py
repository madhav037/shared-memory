"""Known issues: what is broken in a project now and how to work around it, saved straight into project memory.

A known issue skips personal memory and promotion, so every member's agent is warned at once (ADR-0015). The check
promotion exists for still runs: the similar project memories go back to the member's coding agent, which resolves
them before the known issue lands (ADR-0004). A card on the project's board tracks each known issue until it is fixed:
the card the member names, or a new To do card.
"""

from __future__ import annotations

import secrets
from pathlib import PurePosixPath
from typing import Any

from shared_memory.audit import MEMORY_SAVED, Audit
from shared_memory.board import TITLE_LIMIT, Board
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller
from shared_memory.index import SearchIndex
from shared_memory.memory import KNOWN_ISSUE, Area, Memory, level_folder
from shared_memory.service import committer, describe
from shared_memory.store import MemoryStore
from shared_memory.validation import validate

SCHEMA = """
CREATE TABLE IF NOT EXISTS known_issue_saves (
    reference TEXT PRIMARY KEY,
    team TEXT NOT NULL,
    member_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    similar_paths TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
"""

RESOLUTIONS = ("link", "keep_both", "cancel")


class KnownIssues:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        store: MemoryStore,
        index: SearchIndex,
        board: Board,
        audit: Audit,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._index = index
        self._board = board
        self._audit = audit
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def similar_before_saving(
        self,
        caller: Caller,
        title: str,
        summary: str,
        body: str,
        related_files: list[str] | None = None,
        card: int | None = None,
    ) -> dict[str, Any] | None:
        """Saving's first call up to the save: the similar project memories to resolve, or None when there are none.

        It saves no memory, only a pending save, so it need not wait a turn among saves. A caller given None saves
        with no reference, which searches again and lands the known issue in its turn.
        """
        return self._similar(caller, self._known_issue(caller, title, summary, body, related_files, card))

    def titles(self, caller: Caller) -> list[str]:
        """The title of every active known issue in the session's project, as its briefing lists them. Nothing for a
        session outside a project, or in a project the member can't reach."""
        if caller.project is None or caller.project.project_id in caller.unreachable:
            return []
        folder = level_folder("project", KNOWN_ISSUE, caller.project.project_id)
        return [
            memory.title
            for _, memories in self._store.walk(caller.team, folder)
            for _, memory in memories
            if memory.status == "active" and memory.type == KNOWN_ISSUE
        ]

    def save(
        self,
        caller: Caller,
        title: str,
        summary: str,
        body: str,
        related_files: list[str] | None = None,
        reference: str | None = None,
        resolutions: dict[str, str] | None = None,
        card: int | None = None,
    ) -> dict[str, Any]:
        """Save a known issue into project memory and link it to the card that will fix it: the card named, or a new
        To do card. Similar project memories come back first, to be resolved before it lands."""
        memory = self._known_issue(caller, title, summary, body, related_files, card)
        if reference is None:
            proposal = self._similar(caller, memory)
            return proposal if proposal is not None else self._land(caller, memory, card)

        project = caller.require_project()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT similar_paths FROM known_issue_saves WHERE reference = %s AND team = %s AND member_id = %s"
                " AND project_id = %s",
                (reference, caller.team, caller.member_id, project.project_id),
            ).fetchone()
        if row is None:
            raise Refused("Unknown reference for this known issue. Call save_known_issue again without a reference.")
        chosen = dict(resolutions or {})
        if set(chosen) != set(row["similar_paths"]):
            raise Refused(
                "Give a resolution for every similar memory (link, keep_both or cancel): " + ", ".join(row["similar_paths"])
            )
        unknown = sorted({value for value in chosen.values() if value not in RESOLUTIONS})
        if unknown:
            raise Refused(f"Unknown resolution {unknown[0]!r}: use link, keep_both or cancel.")
        if "cancel" in chosen.values():
            self._forget(reference)
            return {"status": "cancelled"}
        linked = sorted(path for path, resolution in chosen.items() if resolution == "link")
        if len(linked) > 1:
            raise Refused("Link to one known issue only; resolve the others as keep_both.")
        if linked:
            existing = self._store.read(caller.team, PurePosixPath(linked[0]))
            if existing.type != KNOWN_ISSUE:
                raise Refused(
                    f"{linked[0]} is a {existing.type}: link only to a known issue. Resolve it as keep_both or cancel."
                )
            if existing.status != "active":
                raise Refused(f"{linked[0]} is no longer active. Call save_known_issue again without a reference.")
            self._forget(reference)
            if card is not None:
                self._board.link_known_issue(caller, card, linked[0])
            return {"status": "linked", "path": linked[0], "card": card}
        self._forget(reference)
        return self._land(caller, memory, card)

    def _known_issue(
        self, caller: Caller, title: str, summary: str, body: str, related_files: list[str] | None, card: int | None
    ) -> Memory:
        caller.require_project()
        memory = Memory(
            title=title.strip(),
            summary=summary.strip(),
            type=KNOWN_ISSUE,
            author=caller.member_id,
            body=body,
            related_files=list(related_files or []),
        )
        validate(memory, self._settings.memory_word_limit)
        if card is not None:
            self._board.require_card(caller, card)
        # Embedded before its save takes a turn; the similar check reads the same vectors.
        self._index.prepare(caller.team, memory)
        return memory

    def _similar(self, caller: Caller, memory: Memory) -> dict[str, Any] | None:
        project = caller.require_project()
        similar = self._index.similar_to(
            caller.team, memory, project_id=project.project_id, threshold=self._settings.similar_threshold
        )
        if not similar:
            return None
        reference = secrets.token_urlsafe(12)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO known_issue_saves (reference, team, member_id, project_id, similar_paths, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (reference, caller.team, caller.member_id, project.project_id, [p for p, _ in similar], self._clock()),
            )
        return {
            "status": "similar_memories",
            "reference": reference,
            "similar": [
                {**describe(PurePosixPath(p), self._store.read(caller.team, PurePosixPath(p))), "similarity": round(s, 3)}
                for p, s in similar
            ],
            "next": "Judge with the member whether each similar memory describes the same problem, then call "
            "save_known_issue again with the same known issue, this reference and a resolution for every similar "
            "memory: link (it is already this known issue, so none is saved), keep_both, or cancel.",
        }

    def _track(self, caller: Caller, memory: Memory, path: str, card: int | None) -> int:
        """Link the known issue to the card named, or to a new To do card, and answer the card's number."""
        if card is not None:
            self._board.link_known_issue(caller, card, path)
            return card
        fix = f"Fix: {memory.title}"
        fix = fix if len(fix) <= TITLE_LIMIT else fix[: TITLE_LIMIT - 3].rstrip() + "..."
        number: int = self._board.add(caller, fix, memory.summary, known_issues=[path])["number"]
        return number

    def _forget(self, reference: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM known_issue_saves WHERE reference = %s", (reference,))

    def _land(self, caller: Caller, memory: Memory, card: int | None) -> dict[str, Any]:
        """Save the known issue into its project's project memory, one commit like any save, with its card.

        Memory is in git and cards in Postgres, so the card is added or linked as part of the save, in the save's own
        transaction: a card that can't be had undoes the save, and no known issue lands without one tracking it.
        """
        project = caller.require_project()
        area = Area("project", project.project_id)
        folder = level_folder("project", KNOWN_ISSUE, project.project_id)
        tracking: list[int] = []
        with self._store.change(caller.team, committer(caller), f"Known issue: {memory.title}", areas=[area]) as change:
            path = change.new_path(folder, memory.title)
            change.write(path, memory)
            change.also(lambda: self._audit.memory(caller, MEMORY_SAVED, str(path), type=memory.type, level="project"))
            change.also(lambda: tracking.append(self._track(caller, memory, str(path), card)))
        (card,) = tracking
        return {
            "status": "saved",
            "path": str(path),
            "level": "project",
            "card": card,
            "next": f"Every member's agent is warned of it now, and card {card} on the board tracks the fix: tell the "
            "member. Retire the known issue once it is fixed.",
        }
