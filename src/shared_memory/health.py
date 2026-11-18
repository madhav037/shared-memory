"""Project health (CONTEXT.md): what a project's memory is doing, for its leads and the team's admins.

A read model only. It owns no table: it asks `Identity` who looks after the project, `Uses` which memory is possibly
outdated (pinned memory left out, as the outdated-memory rule says) and when each was last used, `Challenges`
which memory is in doubt, `FileEdits` and `TiedFiles` which of the files its sessions edited lately no memory is
tied to, the told record which memory recall told the most sessions, and `Popularity` which personal memory is near
the popular-memory bar. Reading it is no use of any memory, and it changes nothing (ADR-0009): pinning, unpinning,
deciding and retiring stay on their own screens.

The project's memory is its project memory, foundations included: what sits under `projects/<id>/shared`. Its
members' personal memory is theirs: a file only a personal memory is tied to is still a coverage gap, while one that
team memory is tied to is not. Personal memory shows only in most relied on, where it is near the popular-memory bar:
the memory a lead may nudge its author to promote.

The interface:

- `of(caller)`: the health of the project the caller was placed in, refused to anyone who doesn't look after it.
- `COVERAGE_DAYS` and `COVERAGE_GAPS_LIMIT`: the window coverage gaps count edits in, and how many they list.
- `RELIED_ON_DAYS` and `RELIED_ON_LIMIT`: the window most relied on counts recalls in, and how many each of its lists
  holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from shared_memory.challenges import Challenges, InDoubt
from shared_memory.errors import Refused
from shared_memory.file_edits import EditedFile, FileEdits
from shared_memory.identity import Caller, Identity, Project
from shared_memory.index import Reach
from shared_memory.locks import named
from shared_memory.memory import Memory
from shared_memory.popularity import Popularity
from shared_memory.store import MemoryStore
from shared_memory.tied import TiedFiles
from shared_memory.told import ToldRecord
from shared_memory.uses import Uses

# Coverage gaps count the edits of the last 30 days, and list the most edited of the files left.
COVERAGE_DAYS = 30
COVERAGE_GAPS_LIMIT = 10
# Most relied on counts the recalls of the last 30 days, and lists the most of each kind.
RELIED_ON_DAYS = 30
RELIED_ON_LIMIT = 10


class NotALead(Refused):
    """Project health is for the project's leads and the team's admins."""

    def __init__(self) -> None:
        super().__init__("Only this project's leads and the team's admins can see its health.")


@dataclass(frozen=True)
class OutdatedMemory:
    """A possibly outdated memory, with when a coding agent last used it (or it was last saved)."""

    path: str
    memory: Memory
    last_used: datetime | None


@dataclass(frozen=True)
class DoubtedMemory:
    """A memory in doubt, with what marks it so: how many members doubt it, and for which reasons."""

    path: str
    memory: Memory
    in_doubt: InDoubt


@dataclass(frozen=True)
class CoverageGap:
    """A file the project's sessions edited in the last `COVERAGE_DAYS` days that no project or team memory is tied
    to, with how many edits changed it."""

    repository: str
    path: str
    edits: int

    @property
    def file(self) -> str:
        """As it is written: repository:path."""
        return named(self.repository, self.path)


@dataclass(frozen=True)
class RecalledMemory:
    """A project memory recall told sessions in the last `RELIED_ON_DAYS` days, with how many sessions."""

    path: str
    memory: Memory
    sessions: int


@dataclass(frozen=True)
class NearlyPopularMemory:
    """A personal memory in the project near the popular-memory bar, with how many other members read it."""

    path: str
    memory: Memory
    readers: int


@dataclass(frozen=True)
class Health:
    """A project's health now: its possibly outdated memory, the longest unused first; its memory in doubt, the most
    doubted first; its coverage gaps, the most edited first; and the memory it relies on most: its project memory
    recalled in the most sessions, and its personal memory nearest the popular-memory bar, each the most first."""

    project: Project
    possibly_outdated: tuple[OutdatedMemory, ...]
    in_doubt: tuple[DoubtedMemory, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    most_recalled: tuple[RecalledMemory, ...]
    nearly_popular: tuple[NearlyPopularMemory, ...]


# Sorts a memory with no last use first: it can only lack one if its use went between the two reads.
_NEVER = datetime.min.replace(tzinfo=UTC)


class ProjectHealth:
    def __init__(
        self,
        identity: Identity,
        store: MemoryStore,
        uses: Uses,
        challenges: Challenges,
        file_edits: FileEdits,
        tied: TiedFiles,
        told: ToldRecord,
        popularity: Popularity,
    ) -> None:
        self._identity = identity
        self._store = store
        self._uses = uses
        self._challenges = challenges
        self._file_edits = file_edits
        self._tied = tied
        self._told = told
        self._popularity = popularity

    def of(self, caller: Caller) -> Health:
        """The health of the project the caller was placed in, which already refused a member a restricted project
        keeps out; this refuses anyone else who isn't one of its leads or the team's admins."""
        project = caller.require_project()
        if not self._identity.looks_after(caller.member, project.project_id):
            raise NotALead()
        memories = self._project_memory(caller.team, project.project_id)
        return Health(
            project,
            self._possibly_outdated(caller.team, memories),
            self._in_doubt(caller.team, memories),
            self._coverage_gaps(caller.team, project.project_id),
            self._most_recalled(project.project_id, memories),
            self._nearly_popular(caller.team, project.project_id),
        )

    def _project_memory(self, team: str, project_id: str) -> dict[str, Memory]:
        return {
            str(path): memory
            for _, held in self._store.walk(team, PurePosixPath("projects", project_id, "shared"))
            for path, memory in held
        }

    def _possibly_outdated(self, team: str, memories: dict[str, Memory]) -> tuple[OutdatedMemory, ...]:
        outdated = self._uses.possibly_outdated(team, {path: memory.status for path, memory in memories.items()})
        listed = [OutdatedMemory(path, memories[path], self._uses.last_used(team, path)) for path in outdated]
        return tuple(sorted(listed, key=lambda one: (one.last_used or _NEVER, one.path)))

    def _in_doubt(self, team: str, memories: dict[str, Memory]) -> tuple[DoubtedMemory, ...]:
        doubted = self._challenges.in_doubt(team, memories)
        listed = [DoubtedMemory(path, memories[path], in_doubt) for path, in_doubt in doubted.items()]
        return tuple(sorted(listed, key=lambda one: (-one.in_doubt.count, one.path)))

    def _coverage_gaps(self, team: str, project_id: str) -> tuple[CoverageGap, ...]:
        """The most edited of the project's files lately that no project or team memory is tied to: one lookup of the
        tied files for each repository edited."""
        edited = self._file_edits.most_edited(project_id, COVERAGE_DAYS)
        by_repository: dict[str, list[EditedFile]] = {}
        for each in edited:
            by_repository.setdefault(each.repository, []).append(each)
        reach = Reach.project_and_team_memory_of(project_id)
        untied = {
            (repository, path)
            for repository, files in by_repository.items()
            for path in self._tied.untied(team, repository, [each.path for each in files], reach)
        }
        gaps = [CoverageGap(each.repository, each.path, each.edits) for each in edited if (each.repository, each.path) in untied]
        return tuple(gaps[:COVERAGE_GAPS_LIMIT])

    def _most_recalled(self, project_id: str, memories: dict[str, Memory]) -> tuple[RecalledMemory, ...]:
        """The project memory still active that recall told the most sessions lately."""
        recalled = self._told.most_recalled(
            str(PurePosixPath("projects", project_id, "shared")), timedelta(days=RELIED_ON_DAYS)
        )
        listed = [
            RecalledMemory(path, memories[path], sessions)
            for path, sessions in recalled
            if path in memories and memories[path].status == "active"
        ]
        return tuple(listed[:RELIED_ON_LIMIT])

    def _nearly_popular(self, team: str, project_id: str) -> tuple[NearlyPopularMemory, ...]:
        """The personal memory still active, in the project, nearest the popular-memory bar."""
        listed: list[NearlyPopularMemory] = []
        for path, readers in self._popularity.nearly_popular(team, project_id):
            try:
                memory = self._store.read(team, PurePosixPath(path))
            except Refused:
                continue
            if memory.status == "active":
                listed.append(NearlyPopularMemory(path, memory, readers))
            if len(listed) == RELIED_ON_LIMIT:
                break
        return tuple(listed)
