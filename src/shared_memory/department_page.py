"""The department page (#636, spec #624): a department's projects and its department memory, and for its department
leads and the company's admins a roll-up of how memory is doing in each of its projects and in department memory.

A read model only. It owns no table: it asks `Departments` which department the member can reach and whether they may
change it, the memory store what memory there is, `Uses` which memory is possibly outdated and which was used within
the window (the counters project health already reads), and `Challenges` what is waiting. Reading it is no use of any
memory, and it changes nothing (ADR-0009).

The roll-up is aggregates only, never per member (spec #624): counts, with no member's name, member ID or author.

The interface:

- `of(caller, department_id)`: the department as the caller sees it, refused when it isn't one they can reach.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from shared_memory.challenges import LEVEL_CONTRADICTION, Challenge, Challenges, project_of
from shared_memory.departments import Department, Departments
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Project, restricted_department
from shared_memory.memory import DEPARTMENTS_FOLDER, Memory
from shared_memory.store import MemoryStore
from shared_memory.uses import Uses

# How far back the roll-up counts memory as used: the last 30 days.
WINDOW_DAYS = 30


@dataclass(frozen=True)
class Counts:
    """How one area's memory is doing: its active memories, how many of them are possibly outdated and how many were
    used within the window, and the level contradictions and other challenges waiting on it."""

    memories: int
    possibly_outdated: int
    used: int
    level_contradictions: int
    challenges: int


@dataclass(frozen=True)
class RollUp:
    """Each project's counts, in the order the department lists them, and department memory's own."""

    projects: tuple[tuple[Project, Counts], ...]
    department_memory: Counts


@dataclass(frozen=True)
class Page:
    """A department as one member sees it. `roll_up` is None for a member who is neither its lead nor an admin."""

    department: Department
    restricted: bool
    you_lead: bool
    projects: tuple[Project, ...]
    memory: tuple[tuple[str, Memory], ...]
    roll_up: RollUp | None


class DepartmentPages:
    def __init__(self, departments: Departments, store: MemoryStore, uses: Uses, challenges: Challenges) -> None:
        self._departments = departments
        self._store = store
        self._uses = uses
        self._challenges = challenges

    def of(self, caller: Caller, department_id: str) -> Page:
        """The department as the caller sees it: refused with the restricted department's own refusal to a member
        outside its access list, and refused as no department when there is none by that ID."""
        view = next(
            (one for one in self._departments.listed(caller.member) if one.department.department_id == department_id),
            None,
        )
        if view is None:
            if self._departments.exists(department_id):
                raise restricted_department(department_id)
            raise Refused(f"{department_id!r} is not a department in your company.")
        folder = PurePosixPath(DEPARTMENTS_FOLDER, department_id)
        memory = self._active(caller.company, folder)
        roll_up = None
        if view.you_may_change:
            roll_up = self._roll_up(caller.company, str(folder), memory, view.projects)
        return Page(
            department=view.department,
            restricted=view.restricted,
            you_lead=view.you_lead,
            projects=tuple(view.projects),
            memory=tuple(sorted(memory.items(), key=lambda one: (one[1].title.lower(), one[0]))),
            roll_up=roll_up,
        )

    def _roll_up(
        self, company: str, folder: str, department_memory: dict[str, Memory], projects: Iterable[Project]
    ) -> RollUp:
        waiting = self._challenges.open_challenges(company)
        listed = tuple(projects)
        return RollUp(
            projects=tuple(
                (
                    project,
                    self._counts(
                        company,
                        self._active(company, PurePosixPath("projects", project.project_id, "shared")),
                        [one for one in waiting if _about_project(one, folder) == project.project_id],
                    ),
                )
                for project in listed
            ),
            department_memory=self._counts(
                company, department_memory, [one for one in waiting if _about_department(one, folder)]
            ),
        )

    def _counts(self, company: str, memories: dict[str, Memory], waiting: list[Challenge]) -> Counts:
        statuses = {path: memory.status for path, memory in memories.items()}
        contradictions = sum(1 for one in waiting if one.kind == LEVEL_CONTRADICTION)
        return Counts(
            memories=len(memories),
            possibly_outdated=len(self._uses.possibly_outdated(company, statuses)),
            used=len(self._uses.used_within(company, memories, WINDOW_DAYS)),
            level_contradictions=contradictions,
            challenges=len(waiting) - contradictions,
        )

    def _active(self, company: str, root: PurePosixPath) -> dict[str, Memory]:
        return {
            str(path): memory
            for _, held in self._store.walk(company, root)
            for path, memory in held
            if memory.status == "active"
        }


def _subject(challenge: Challenge) -> str | None:
    """The memory a challenge waits on: a level contradiction's narrower memory, whose leads decide it, or otherwise
    the memory (or, for a promotion into department memory, the department's folder) it stands against."""
    return challenge.challenger_path if challenge.kind == LEVEL_CONTRADICTION else challenge.target_path


def _about_department(challenge: Challenge, folder: str) -> bool:
    subject = _subject(challenge)
    return subject is not None and (subject == folder or subject.startswith(f"{folder}/"))


def _about_project(challenge: Challenge, folder: str) -> str | None:
    """The project a challenge waits on, or None when it waits on department memory or on none of the projects."""
    return None if _about_department(challenge, folder) else project_of(challenge)
