"""How the console shows the team's memory: folder names, what each folder is, and the order they read in.

None of this is what a session does with memory, which is `service.py`. It is presentation for one web page — the
console's explorer — so a change to how that page reads lands here rather than in the module every coding agent's
session depends on.
"""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from shared_memory.challenges import Challenges
from shared_memory.identity import Caller, Identity, project_in
from shared_memory.memory import Memory, locate
from shared_memory.store import MemoryStore
from shared_memory.uses import Uses

TYPE_NAMES = {
    "conventions": "Conventions",
    "decisions": "Decisions",
    "architecture": "Architecture",
    "gotchas": "Gotchas",
    "known-issues": "Known issues",
}


def accepted_first(folder: PurePosixPath) -> tuple[tuple[int, str], ...]:
    """Folders in path order, except that a project's accepted memory comes before its members' personal memory."""
    return tuple((1 if part == "people" else 0, part) for part in folder.parts)


def folder_kind(folder: PurePosixPath) -> str:
    """What a memory folder is: team or project, project or personal memory, a member's, a type, or a topic."""
    parts = folder.parts
    if parts[:1] == ("team",):
        return ("team", "type")[len(parts) - 1] if len(parts) <= 2 else "topic"
    if parts == ("projects",):
        return "projects"
    kinds = {2: "project", 3: "shared" if parts[2:3] == ("shared",) else "people"}
    if len(parts) in kinds:
        return kinds[len(parts)]
    if parts[2:3] == ("shared",):
        return "type" if len(parts) == 4 else "topic"
    return {4: "member", 5: "type"}.get(len(parts), "topic")


def folder_name(folder: PurePosixPath, projects: dict[str, str], people: dict[str, str]) -> str:
    """A folder's name as a member would say it, rather than as it is spelled on disk."""
    kind = folder_kind(folder)
    last = folder.name
    return {
        "team": "Team memory",
        "projects": "Projects",
        "project": projects.get(last, last),
        "shared": "Project memory",
        "people": "Personal memory",
        "member": people.get(last, last),
        "type": TYPE_NAMES.get(last, last),
    }.get(kind, last)


class ConsoleMemory:
    """The team's memory as the console's explorer lays it out."""

    def __init__(self, identity: Identity, store: MemoryStore, challenges: Challenges, uses: Uses) -> None:
        self._identity = identity
        self._store = store
        self._challenges = challenges
        self._uses = uses

    def explore(self, caller: Caller, folder: str, deep: bool = False) -> dict[str, Any]:
        """One folder of the team's memory for the console's explorer.

        The top holds team memory and every project this member can reach. Each subfolder says how many memories it
        holds and when they last changed, so the structure reads without opening it. Asked for deep, it also sets out
        every folder beneath it with the memories in each, so a whole part of the contents reads on one page.
        """
        pure = PurePosixPath(folder.replace("\\", "/").strip("/"))
        caller.require_reach(str(pure))
        reachable = {project.project_id: project.name for project in self._identity.projects(caller.member)}
        people = {one["member_id"]: one["name"] for one in self._identity.members(caller.member)}
        memories: list[tuple[PurePosixPath, Memory]] = []
        if not pure.parts:
            subfolders = [PurePosixPath("team")] + [PurePosixPath("projects", project) for project in reachable]
        elif pure.parts == ("projects",):
            subfolders = [PurePosixPath("projects", project) for project in reachable]
        else:
            memories, subfolders = self._store.list_folder(caller.team, pure)
            subfolders = sorted(
                (sub for sub in subfolders if project_in(str(sub)) not in caller.unreachable), key=accepted_first
            )
        inside = []
        if deep and pure.parts and pure.parts != ("projects",):
            for below, held in self._store.walk(caller.team, pure):
                if below == pure or project_in(str(below)) in caller.unreachable:
                    continue
                count, changed = self._store.extent(caller.team, below)
                inside.append(
                    {
                        "path": str(below),
                        "name": folder_name(below, reachable, people),
                        "kind": folder_kind(below),
                        "depth": len(below.parts) - len(pure.parts),
                        "count": count,
                        "changed": changed,
                        "memories": self._entries(caller, held, people),
                    }
                )
        inside.sort(key=lambda section: accepted_first(PurePosixPath(str(section["path"]))))
        folders = []
        for sub in subfolders:
            count, changed = self._store.extent(caller.team, sub)
            folders.append(
                {
                    "path": str(sub),
                    "name": folder_name(sub, reachable, people),
                    "kind": folder_kind(sub),
                    "memories": count,
                    "changed": changed,
                }
            )
        return {
            "folder": str(pure) if pure.parts else "",
            "name": folder_name(pure, reachable, people) if pure.parts else "Memory",
            "kind": folder_kind(pure) if pure.parts else "root",
            "trail": [
                {"path": str(PurePosixPath(*pure.parts[:depth])), "name": folder_name(PurePosixPath(*pure.parts[:depth]), reachable, people)}
                for depth in range(1, len(pure.parts))
                if pure.parts[:depth] != ("projects",)
            ],
            "folders": folders,
            "memories": self._entries(caller, memories, people),
            "inside": inside,
        }

    def _entries(
        self, caller: Caller, memories: list[tuple[PurePosixPath, Memory]], people: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Memories as a folder lists them: what each is, who wrote it, when it changed and what is disputed."""
        pending = self._challenges.pending(caller.team, [str(path) for path, _ in memories])
        # One query for the team's open challenges, not one per memory: a deep folder lists hundreds.
        challenged = Counter(challenge.target_path for challenge in self._challenges.open_challenges(caller.team))
        outdated = self._uses.possibly_outdated(caller.team, {str(path): memory.status for path, memory in memories})
        return [
            {
                "path": str(path),
                "title": memory.title,
                "summary": memory.summary,
                "type": memory.type,
                "level": locate(str(path)).level,
                "status": memory.status,
                "author": memory.author,
                "author_name": people.get(memory.author, memory.author),
                "changed": self._store.changed(caller.team, path),
                "challenged": challenged[str(path)],
                "waiting": bool(pending[str(path)]),
                "possibly_outdated": str(path) in outdated,
            }
            for path, memory in memories
        ]
