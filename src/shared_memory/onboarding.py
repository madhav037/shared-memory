"""Onboarding: the steps a member's coding agent follows to import their existing setup into memory.

The server only hands the steps over. Reading the sources, cutting them into memories and judging what contradicts
what happen in the member's session (ADR-0004), with the same tools any session uses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from importlib import resources
from pathlib import PurePosixPath
from typing import Any

from shared_memory import sources
from shared_memory.audit import Audit
from shared_memory.clock import Clock
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import NAME_PATTERN, Caller, Identity
from shared_memory.memory import FOUNDATIONS_FOLDER
from shared_memory.store import MemoryStore


MODES = {"interactive": "onboarding.md", "headless": "onboarding_headless.md"}


def steps(mode: str = "interactive") -> str:
    """The onboarding steps, the one text behind the `onboard` tool and the `onboard` prompt. The skills only point
    at it, so every coding agent follows the same steps. Headless steps write a proposals file and save nothing
    (ADR-0030)."""
    if mode not in MODES:
        raise Refused(f"mode {mode!r} is not one of {', '.join(MODES)}: interactive with a member, headless in CI.")
    return resources.files("shared_memory").joinpath(MODES[mode]).read_text(encoding="utf-8")


STATUSES = ("not_started", "partly_done", "done")

SCHEMA = """
-- The latest onboarding progress per project and entry: one repository, or one kind of outside source. The empty
-- string stands for the one an entry isn't, so the key is one row per entry.
CREATE TABLE IF NOT EXISTS onboarding_progress (
    team TEXT NOT NULL,
    project_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    outside_source TEXT NOT NULL,
    status TEXT NOT NULL,
    left_out INTEGER NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (team, project_id, repository, outside_source)
);
"""


@dataclass(frozen=True)
class Entry:
    """How far onboarding has got for one repository or one kind of outside source of a project: its latest status,
    who recorded it and when, and its counts. Promoted and waiting on a challenge come from the audit log."""

    repository: str | None
    outside_source: str | None
    status: str
    left_out: int
    recorded_by: str
    recorded_at: datetime
    promoted: int
    waiting_on_challenge: int

    def counts(self, source: str) -> bool:
        if self.repository is not None:
            return sources.of_repository(source, self.repository)
        assert self.outside_source is not None
        return sources.of_kind(source, self.outside_source)


class Progress:
    """Onboarding progress: recorded by a session, read by the next run's steps and by project settings."""

    def __init__(self, db: Database, identity: Identity, audit: Audit, clock: Clock) -> None:
        self._db = db
        self._identity = identity
        self._audit = audit
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def record(
        self,
        caller: Caller,
        status: str,
        repository: str | None = None,
        outside_source: str | None = None,
        left_out: int = 0,
    ) -> dict[str, Any]:
        """Record the latest progress for one entry of the caller's project, replacing what was recorded before."""
        project = caller.require_project()
        if (repository is None) == (outside_source is None):
            raise Refused(
                "Record progress for one entry: pass repository, a repository's name, or outside_source, one of "
                f"{', '.join(sources.OUTSIDE_KINDS)}, and not both."
            )
        if repository is not None and not NAME_PATTERN.match(repository):
            raise Refused(f"{repository!r} is not a repository name, for example billing-api.")
        if outside_source is not None and outside_source not in sources.OUTSIDE_KINDS:
            raise Refused(f"outside_source must be one of {', '.join(sources.OUTSIDE_KINDS)}.")
        if status not in STATUSES:
            raise Refused(f"status must be one of {', '.join(STATUSES)}.")
        if left_out < 0:
            raise Refused("left_out is how many passages you left out, so it can't be below zero.")
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO onboarding_progress (team, project_id, repository, outside_source, status, left_out,"
                " recorded_by, recorded_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (team, project_id, repository, outside_source) DO UPDATE SET status = EXCLUDED.status,"
                " left_out = EXCLUDED.left_out, recorded_by = EXCLUDED.recorded_by,"
                " recorded_at = EXCLUDED.recorded_at",
                (
                    caller.company, project.project_id, repository or "", outside_source or "", status, left_out,
                    caller.member_id, self._clock(),
                ),  # fmt: skip
            )
        return {"status": status, "repository": repository, "outside_source": outside_source, "left_out": left_out}

    def entries(self, caller: Caller) -> tuple[bool, list[Entry]]:
        """The caller's project's entries, repositories first, with whether they are every entry: the project's
        leads and the company's admins see all of them, any other member only the ones they recorded."""
        project = caller.require_project()
        everyone = self._identity.looks_after(caller.member, project.project_id)
        return everyone, [
            one for one in self.of_project(caller) if everyone or one.recorded_by == caller.member_id
        ]

    def of_project(self, caller: Caller) -> list[Entry]:
        """Every entry of the caller's project, for the steps of the next run, which skip what is done."""
        project = caller.require_project()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT repository, outside_source, status, left_out, recorded_by, recorded_at"
                " FROM onboarding_progress WHERE team = %s AND project_id = %s"
                " ORDER BY repository = '', repository, outside_source",
                (caller.company, project.project_id),
            ).fetchall()
        promoted, waiting = self._audit.imports_in(caller.member.company_pk, project.project_id)
        found = []
        for row in rows:
            entry = Entry(
                repository=row["repository"] or None,
                outside_source=row["outside_source"] or None,
                status=row["status"],
                left_out=row["left_out"],
                recorded_by=row["recorded_by"],
                recorded_at=row["recorded_at"],
                promoted=0,
                waiting_on_challenge=0,
            )
            found.append(
                replace(
                    entry,
                    promoted=sum(1 for source in promoted if entry.counts(source)),
                    waiting_on_challenge=sum(1 for source in waiting if entry.counts(source)),
                )
            )
        return found


def progress_so_far(entries: list[Entry]) -> str:
    """The steps' closing section: what earlier runs recorded, so this run skips what is done."""
    lines = ["## Progress so far", ""]
    if not entries:
        lines.append("No run has recorded progress in this project yet.")
    for one in entries:
        name = one.repository if one.repository is not None else f"outside source {one.outside_source}"
        lines.append(
            f"- {name}: {one.status}, recorded by {one.recorded_by} on {one.recorded_at.date().isoformat()}; "
            f"{one.promoted} promoted, {one.waiting_on_challenge} waiting on a challenge, {one.left_out} left out"
        )
    return "\n".join(lines) + "\n"


OFFER = (
    "[onboarding] This project has no project memory yet: `onboard` imports what the company already has. Offer it once; "
    "start it only if the member asks."
)


def has_project_memory(store: MemoryStore, company: str, project_id: str) -> bool:
    """Whether the project holds any active project memory beyond its foundations."""
    project_memory = PurePosixPath("projects", project_id, "shared")
    foundations = project_memory / FOUNDATIONS_FOLDER
    for folder, memories in store.walk(company, project_memory):
        if folder == foundations or foundations in folder.parents:
            continue
        if any(memory.status == "active" for _, memory in memories):
            return True
    return False


def offer(caller: Caller, store: MemoryStore, audit: Audit) -> list[str]:
    """The briefing's onboarding line: for a session whose project has no project memory and whose member has
    imported nothing from its repository. It goes once either changes."""
    project, repository = caller.project, caller.repository
    if project is None or project.project_id in caller.unreachable:
        return []
    if repository is not None and audit.has_imported_from(caller, repository):
        return []
    if has_project_memory(store, caller.company, project.project_id):
        return []
    return [OFFER]
