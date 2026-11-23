"""Pins and the briefing every session receives when it starts."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from shared_memory.audit import MEMORY_PINNED, MEMORY_UNPINNED, Audit
from shared_memory.challenges import Challenges, InDoubt
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database, moved_prefix
from shared_memory.departments import Departments
from shared_memory.errors import Refused
from shared_memory.identity import Caller
from shared_memory.index import overridden
from shared_memory.memory import COMPANY_FOLDER, DEPARTMENTS_FOLDER, FOLDER_TYPES, Memory, locate
from shared_memory.fence import escape, fenced, new_token, one_line
from shared_memory.recall import framing
from shared_memory.store import MemoryStore
from shared_memory.suspected import label_for, reasons_for

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
-- Set on a pin of department memory alone (ADR-0032): the sessions of that department's projects are briefed with it.
ALTER TABLE pins ADD COLUMN IF NOT EXISTS department_id TEXT;
"""


ONLY_ACCEPTED = (
    "Only project, department and company memory can be pinned, so the briefing holds accepted memory."
)


@dataclass(frozen=True)
class PinTarget:
    path: str
    kind: str
    level: str
    project_id: str | None
    department_id: str | None = None


# Whose briefings a pin reaches: a project's sessions, with that project's department, or (None, department) for the
# department's pins alone, or (None, None) for company pins alone.
Briefed = tuple[str | None, str | None]


@dataclass(frozen=True)
class Work:
    """What the board adds to a member's briefing, one short line each: their cards overdue or due today, their other
    cards in Doing and Blocked, and the titles of their project's active known issues."""

    due: list[str] = field(default_factory=list)
    working: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)


# Room kept within the cap for the line counting the work that didn't fit.
COUNTS_TOKENS = 50


def estimate_tokens(text: str) -> int:
    """About four characters to a token."""
    return (len(text) + 3) // 4


def _work_sections(work: Work, sessions: list[str], budget: int) -> list[str]:
    """The member's work and then the project's other active sessions, part by part in order, each line only while it
    fits in the budget. Once a line doesn't fit, it and every line after it are counted instead."""
    parts = [
        ("[your cards] Overdue or due today:", work.due, "cards"),
        ("[your cards] In Doing and Blocked:", work.working, "cards"),
        (
            "[known issues] Broken in this project now; search memory for a workaround:",
            [f"- {title}" for title in work.known_issues],
            "known issues",
        ),
        ("[active sessions] Other sessions in this project now, each with its member ID and activity:", sessions, "sessions"),
    ]
    budget -= COUNTS_TOKENS
    sections: list[str] = []
    left = {"cards": 0, "known issues": 0, "sessions": 0}
    full = False
    for heading, lines, kind in parts:
        shown: list[str] = []
        # Each line carries members' words (a card's title, a known issue's, a name, an activity): escaped, one line.
        for line in map(one_line, lines):
            cost = estimate_tokens(line) + 1 + (0 if shown else estimate_tokens(heading) + 1)
            if not full and cost <= budget:
                shown.append(line)
                budget -= cost
                continue
            full = True
            left[kind] += 1
        if shown:
            sections.append("\n".join([heading, *shown]))
    counted = []
    if left["cards"]:
        counted.append(f"{left['cards']} more of your cards")
    if left["known issues"]:
        counted.append(f"{left['known issues']} more known issue{'' if left['known issues'] == 1 else 's'}")
    if left["sessions"]:
        counted.append(f"{left['sessions']} more active session{'' if left['sessions'] == 1 else 's'}")
    if counted:
        listed = ", ".join(counted[:-1]) + " and " + counted[-1] if len(counted) > 1 else counted[0]
        pointer = (
            ": the board tool lists your cards, and search finds the known issues."
            if left["cards"] or left["known issues"]
            else "."
        )
        sections.append(f"[briefing cap] {listed} did not fit within the briefing cap{pointer}")
    return sections


def pin_target(path: str) -> PinTarget:
    cleaned = path.replace("\\", "/").strip("/")
    if cleaned.endswith(".md"):
        location = locate(cleaned)
        if location.level == "personal":
            raise Refused(ONLY_ACCEPTED)
        return PinTarget(str(location.path), "memory", location.level, location.project_id, location.department_id)
    parts = PurePosixPath(cleaned).parts
    if ".." not in parts and len(parts) == 3 and parts[0] == COMPANY_FOLDER and parts[1] in FOLDER_TYPES:
        return PinTarget(cleaned, "topic", "company", None)
    if ".." not in parts and len(parts) == 3 and parts[0] == DEPARTMENTS_FOLDER and parts[2] in FOLDER_TYPES:
        return PinTarget(cleaned, "topic", "department", None, parts[1])
    if ".." not in parts and len(parts) == 5 and parts[0] == "projects" and parts[2] == "shared" and parts[3] in FOLDER_TYPES:
        return PinTarget(cleaned, "topic", "project", parts[1])
    if len(parts) >= 3 and parts[0] == "projects" and parts[2] == "people":
        raise Refused(ONLY_ACCEPTED)
    raise Refused(f"{path!r} is neither a project, department or company memory nor a topic folder.")


class Briefing:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        store: MemoryStore,
        audit: Audit,
        clock: Clock,
        challenges: Challenges,
        departments: Departments,
    ) -> None:
        self._settings = settings
        self._departments = departments
        self._challenges = challenges
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
        [rendered] = self._rendered(caller.company, [target], unreachable=caller.unreachable)
        if rendered is None:
            raise Refused(f"There is no active memory or topic at {target.path!r} to pin.")
        with self._db.transaction() as conn:
            if conn.execute("SELECT 1 FROM pins WHERE team = %s AND path = %s", (caller.company, target.path)).fetchone():
                raise Refused(f"{target.path} is already pinned.")
            pinned_at = conn.execute(
                "SELECT DISTINCT level, project_id, department_id FROM pins WHERE team = %s"
                " AND level IN ('project', 'department')",
                (caller.company,),
            ).fetchall()
        cap = self._settings.briefing_cap_tokens
        over = []
        for project_id, department_id in self._reached(target, pinned_at):
            pinned = self._pinned(caller.company, project_id, department_id)
            framed = estimate_tokens(framing(new_token()))
            if framed + sum(tokens for _, tokens in pinned) + estimate_tokens(rendered) > cap:
                over.append(pinned)
        if over:
            # Every briefing is checked, but only one whose pins the member reaches is listed to them.
            seen = next((pinned for pinned in over if all(caller.reaches(pin_path) for pin_path, _ in pinned)), None)
            if seen is None:
                raise Refused(
                    f"Pinning this (about {estimate_tokens(rendered)} tokens) would put a briefing you can't see over "
                    f"its cap of about {cap} tokens."
                )
            listing = "; ".join(f"{pin_path} (about {tokens} tokens)" for pin_path, tokens in seen) or "nothing"
            raise Refused(
                f"Pinning this (about {estimate_tokens(rendered)} tokens) would put the briefing over its cap of about "
                f"{cap} tokens. Unpin something first. Pinned now: {listing}."
            )
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO pins (team, path, kind, level, project_id, department_id, pinned_by, pinned_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    caller.company,
                    target.path,
                    target.kind,
                    target.level,
                    target.project_id,
                    target.department_id,
                    caller.member_id,
                    self._clock(),
                ),
            )
        self._audit.memory(caller, MEMORY_PINNED, target.path, pinned=target.kind, level=target.level)
        return {"pinned": target.path}

    def _reached(self, target: PinTarget, pinned_at: list[dict[str, Any]]) -> set[Briefed]:
        """The briefings a new pin would join, each checked against the cap: every one for a company pin, the
        department's projects' for a department pin, and the project's own for a project pin."""
        projects = [row["project_id"] for row in pinned_at if row["level"] == "project"]
        if target.project_id is not None:
            projects.append(target.project_id)
        departments = self._departments.of_projects(projects)

        def department_of(project_id: str) -> str | None:
            found = departments.get(project_id)
            return None if found is None else found.department_id

        briefed: set[Briefed] = {(None, None)}
        briefed |= {(project_id, department_of(project_id)) for project_id in projects}
        briefed |= {(None, row["department_id"]) for row in pinned_at if row["level"] == "department"}
        if target.level == "project":
            assert target.project_id is not None
            return {(target.project_id, department_of(target.project_id))}
        if target.level == "department":
            return {one for one in briefed if one[1] == target.department_id} | {(None, target.department_id)}
        return briefed

    def unpin(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        cleaned = path.replace("\\", "/").strip("/")
        caller.require_reach(cleaned)
        with self._db.transaction() as conn:
            deleted = conn.execute("DELETE FROM pins WHERE team = %s AND path = %s", (caller.company, cleaned)).rowcount
        if not deleted:
            raise Refused(f"{cleaned} is not pinned.")
        self._audit.memory(caller, MEMORY_UNPINNED, cleaned)
        return {"unpinned": cleaned}

    def pinned_paths(self, company: str) -> set[str]:
        """Every path this company has pinned, for marking up what the console shows."""
        with self._db.transaction() as conn:
            rows = conn.execute("SELECT path FROM pins WHERE team = %s", (company,)).fetchall()
        return {row["path"] for row in rows}

    def pinned_among(self, company: str, paths: Iterable[str]) -> set[str]:
        """Which of these memories are pinned, by themselves or by the topic folder they sit in."""
        folders = {path: str(PurePosixPath(path).parent) for path in paths}
        if not folders:
            return set()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT path FROM pins WHERE team = %s AND path = ANY(%s)",
                (company, [*folders, *set(folders.values())]),
            ).fetchall()
        pinned = {row["path"] for row in rows}
        return {path for path, folder in folders.items() if path in pinned or folder in pinned}

    def listed(self, caller: Caller) -> list[dict[str, Any]]:
        """Everything pinned that this project's sessions are briefed with, oldest pin first."""
        project = caller.require_project()
        # Before the transaction: it takes a connection of its own, and two held at once can run the pool dry.
        department_id = self._department_of(project.project_id)
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT path, kind, level, project_id, department_id, pinned_by, pinned_at FROM pins WHERE team = %s"
                " AND (level = 'company' OR project_id = %s OR (level = 'department' AND department_id = %s))"
                " ORDER BY pinned_at, path",
                (caller.company, project.project_id, department_id),
            ).fetchall()
        targets = [
            PinTarget(row["path"], row["kind"], row["level"], row["project_id"], row["department_id"]) for row in rows
        ]
        pins = []
        for row, target, rendered in zip(rows, targets, self._rendered(caller.company, targets, unreachable=caller.unreachable), strict=True):
            pins.append(
                {
                    "path": target.path,
                    "kind": target.kind,
                    "level": target.level,
                    "title": self._name(caller.company, target),
                    "tokens": estimate_tokens(rendered) if rendered else 0,
                    "pinned_by": row["pinned_by"],
                    "pinned_at": row["pinned_at"],
                }
            )
        return pins

    def _name(self, company: str, target: PinTarget) -> str:
        """What to call a pin: the memory's title, or the topic folder's name."""
        if target.kind == "memory":
            try:
                return self._store.read(company, PurePosixPath(target.path)).title
            except Refused:
                return PurePosixPath(target.path).stem
        return PurePosixPath(target.path).name

    @contextmanager
    def on_change(
        self, company: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> Iterator[None]:
        """Pins follow memory: a pin moves to whatever supersedes its memory and goes away when it is retired.

        They follow in one transaction, which commits only once the save has landed everywhere else."""
        with self._db.transaction() as conn:
            for path, memory in writes.items():
                if memory.status == "superseded" and memory.superseded_by:
                    new = locate(memory.superseded_by)
                    conn.execute(
                        "UPDATE pins SET path = %s, level = %s, project_id = %s, department_id = %s"
                        " WHERE team = %s AND path = %s",
                        (str(new.path), new.level, new.project_id, new.department_id, company, str(path)),
                    )
                elif memory.status == "retired":
                    conn.execute("DELETE FROM pins WHERE team = %s AND path = %s", (company, str(path)))
            yield

    def for_session(
        self,
        caller: Caller,
        extra: list[str] | None = None,
        work: Work | None = None,
        followed_by: str | None = None,
        sessions: list[str] | None = None,
    ) -> str | None:
        """The briefing: pinned memories for the session's project within the cap, any extra notices, then the member's
        work from the board and, last, the project's other active sessions (one line each) in what is left of the cap,
        with counts of what didn't fit. What the session is told right after its briefing (followed_by) is not in it,
        but takes its room out of what is left for the work."""
        if caller.project is None:
            return None
        token = new_token()
        budget = self._settings.briefing_cap_tokens - estimate_tokens(framing(token))
        sections: list[str] = []
        left_out: list[str] = []
        project_id = caller.project.project_id
        department_id = self._department_of(project_id)
        # A broader memory an exception overrides here is left out in favour of the exception.
        left_for_exceptions = overridden(self._db, caller.company, project_id, department_id)
        for path, text in self._pinned_texts(
            caller.company, project_id, department_id, token, left_for_exceptions, caller.unreachable
        ):
            if estimate_tokens(text) <= budget:
                sections.append(text)
                budget -= estimate_tokens(text)
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
        budget -= sum(estimate_tokens(note) for note in notes)
        if followed_by:
            budget -= estimate_tokens(followed_by) + 1
        sections.extend(_work_sections(work or Work(), sessions or [], budget))
        if not sections:
            return None
        return "<shared-memory-briefing>\n" + framing(token) + "\n\n" + "\n\n".join(sections) + "\n</shared-memory-briefing>"

    def _department_of(self, project_id: str) -> str | None:
        found = self._departments.of_project(project_id)
        return None if found is None else found.department_id

    def _rows(self, company: str, project_id: str | None, department_id: str | None) -> list[PinTarget]:
        """The pins a project's sessions are briefed with: company pins, its department's and its own. A project in no
        department matches no department pin, so it is briefed exactly as before departments."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT path, kind, level, project_id, department_id FROM pins WHERE team = %s"
                " AND (level = 'company' OR project_id = %s OR (level = 'department' AND department_id = %s))"
                " ORDER BY pinned_at, path",
                (company, project_id, department_id),
            ).fetchall()
        return [
            PinTarget(row["path"], row["kind"], row["level"], row["project_id"], row["department_id"]) for row in rows
        ]

    def _pinned_texts(
        self,
        company: str,
        project_id: str | None,
        department_id: str | None,
        token: str,
        leaving_out: set[str] | None = None,
        unreachable: frozenset[str] = frozenset(),
    ) -> list[tuple[str, str]]:
        """(path, rendered text) for each pin visible from a project in a department, oldest first, leaving out the
        memories in `leaving_out`, as a member who can't reach the projects in `unreachable` is shown them."""
        targets = self._rows(company, project_id, department_id)
        rendered_all = self._rendered(company, targets, token, leaving_out, unreachable)
        return [
            (target.path, rendered)
            for target, rendered in zip(targets, rendered_all, strict=True)
            if rendered is not None
        ]

    def _pinned(self, company: str, project_id: str | None, department_id: str | None) -> list[tuple[str, int]]:
        """(path, approximate tokens) for each pin visible from a project in a department."""
        return [
            (path, estimate_tokens(text))
            for path, text in self._pinned_texts(company, project_id, department_id, new_token())
        ]

    def _shown(self, company: str, target: PinTarget) -> list[tuple[str, Memory]]:
        """The active memories a pin shows, by path: its memory, or those in its topic folder."""
        if target.kind == "memory":
            try:
                memory = self._store.read(company, PurePosixPath(target.path))
            except Refused:
                return []
            return [(target.path, memory)] if memory.status == "active" else []
        memories, _ = self._store.list_folder(company, PurePosixPath(target.path))
        return [(str(path), memory) for path, memory in memories if memory.status == "active"]

    def _rendered(
        self,
        company: str,
        targets: list[PinTarget],
        token: str | None = None,
        leaving_out: set[str] | None = None,
        unreachable: frozenset[str] = frozenset(),
    ) -> list[str | None]:
        """Each pin as the briefing shows it, or None for one with nothing active to show. Which of their memories are
        in doubt is asked once for them all."""
        out = leaving_out or set()
        shown = [[(path, memory) for path, memory in self._shown(company, target) if path not in out] for target in targets]
        in_doubt = self._challenges.in_doubt(company, [path for memories in shown for path, _ in memories], unreachable)
        return [
            _render(target, memories, token or new_token(), in_doubt)
            for target, memories in zip(targets, shown, strict=True)
        ]


def _render(target: PinTarget, memories: list[tuple[str, Memory]], token: str, in_doubt: dict[str, InDoubt]) -> str | None:
    """One pin's text: a memory in full, or a topic's memories one line each, each memory in doubt marked so."""
    if not memories:
        return None
    if target.kind == "memory":
        [(path, memory)] = memories
        warning = f" [{label_for(reasons)}]" if (reasons := reasons_for(memory)) else ""
        doubted = f"\n{escape(marked.line())}" if (marked := in_doubt.get(path)) else ""
        return f"[{target.level} memory] {escape(memory.title)} ({target.path}){warning}{doubted}\n{fenced(memory.body, token)}"
    lines = [
        f"- {escape(memory.title)}: {fenced(memory.summary, token, inline=True)}"
        + (f" [{label_for(reasons)}]" if (reasons := reasons_for(memory)) else "")
        + (f" {escape(marked.line())}" if (marked := in_doubt.get(path)) else "")
        for path, memory in memories
    ]
    name = PurePosixPath(target.path).name
    return f"[{target.level} memory topic] {name} ({target.path})\n" + "\n".join(lines)


def move_paths(conn: Conn, old: str, new: str) -> None:
    """Keep what is pinned under the folder `old` pinned at the folder `new`, where it moved (`company_move.py`)."""
    conn.execute(
        "UPDATE pins SET path = %(new)s || substr(path, %(after)s) WHERE path LIKE %(old)s", moved_prefix(old, new)
    )


def rename_level(conn: Conn, old: str, new: str) -> None:
    """Say the level `old` as `new` in what is pinned: company memory's level was `team` before the
    rename (`company_move.py`)."""
    conn.execute("UPDATE pins SET level = %s WHERE level = %s", (new, old))
