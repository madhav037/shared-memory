"""Project health (CONTEXT.md): what a project's memory is doing, for its leads and the team's admins.

A read model only. It owns no table: it asks `Identity` who looks after the project, `Uses` which memory is possibly
outdated (pinned memory left out, as the outdated-memory rule says) and when each was last used, and `Challenges`
which memory is in doubt. Reading it is no use of any memory, and it changes nothing (ADR-0009): pinning, unpinning,
deciding and retiring stay on their own screens.

The project's memory is its project memory, foundations included: what sits under `projects/<id>/shared`. Its
members' personal memory is theirs.

The interface:

- `of(caller)`: the health of the project the caller was placed in, refused to anyone who doesn't look after it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from shared_memory.challenges import Challenges, InDoubt
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Project
from shared_memory.memory import Memory
from shared_memory.store import MemoryStore
from shared_memory.uses import Uses


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
class Health:
    """A project's health now: its possibly outdated memory, the longest unused first, and its memory in doubt, the
    most doubted first."""

    project: Project
    possibly_outdated: tuple[OutdatedMemory, ...]
    in_doubt: tuple[DoubtedMemory, ...]


# Sorts a memory with no last use first: it can only lack one if its use went between the two reads.
_NEVER = datetime.min.replace(tzinfo=UTC)


class ProjectHealth:
    def __init__(self, identity: Identity, store: MemoryStore, uses: Uses, challenges: Challenges) -> None:
        self._identity = identity
        self._store = store
        self._uses = uses
        self._challenges = challenges

    def of(self, caller: Caller) -> Health:
        """The health of the project the caller was placed in, which already refused a member a restricted project
        keeps out; this refuses anyone else who isn't one of its leads or the team's admins."""
        project = caller.require_project()
        if not self._identity.looks_after(caller.member, project.project_id):
            raise NotALead()
        memories = self._project_memory(caller.team, project.project_id)
        return Health(project, self._possibly_outdated(caller.team, memories), self._in_doubt(caller.team, memories))

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
