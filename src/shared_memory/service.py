"""What a member's session can do with memory, and the rules that apply."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from shared_memory.audit import MEMORY_DELETED, MEMORY_EDITED, MEMORY_SAVED, Audit
from shared_memory.challenges import Challenges
from shared_memory.config import Settings
from shared_memory.connection import claude_settings, connection_kit
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, check_name, project_in
from shared_memory.index import Hit, SearchIndex, split_sections
from shared_memory.memory import Location, Memory, level_folder, locate, slugify
from shared_memory.store import Committer, MemoryStore
from shared_memory.validation import validate


def committer(caller: Caller) -> Committer:
    return Committer(caller.member_id, caller.member.name, caller.agent)


def describe(path: PurePosixPath, memory: Memory) -> dict[str, Any]:
    location = locate(str(path))
    return {
        "path": str(path),
        "level": location.level,
        "project_id": location.project_id,
        "title": memory.title,
        "summary": memory.summary,
        "type": memory.type,
        "author": memory.author,
        "status": memory.status,
        "replaces": memory.replaces,
        "superseded_by": memory.superseded_by,
        "exception_to": memory.exception_to,
        "related_files": memory.related_files,
        "promoted_by": memory.promoted_by,
        "body": memory.body,
    }


TYPE_NAMES = {"conventions": "Conventions", "decisions": "Decisions", "architecture": "Architecture", "gotchas": "Gotchas"}


def _accepted_first(folder: PurePosixPath) -> tuple[tuple[int, str], ...]:
    """Folders in path order, except that a project's accepted memory comes before its members' personal memory."""
    return tuple((1 if part == "people" else 0, part) for part in folder.parts)


def _folder_kind(folder: PurePosixPath) -> str:
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


def _folder_name(folder: PurePosixPath, projects: dict[str, str], people: dict[str, str]) -> str:
    """A folder's name as a member would say it, rather than as it is spelled on disk."""
    kind = _folder_kind(folder)
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


def label(caller: Caller, level: str, member_id: str | None) -> str:
    if level == "team":
        return "team memory"
    if level == "project":
        return "project memory"
    if member_id == caller.member_id:
        return "your personal memory"
    return f"personal memory of {member_id}, not accepted by the team"


class MemoryService:
    def __init__(
        self,
        settings: Settings,
        identity: Identity,
        store: MemoryStore,
        index: SearchIndex,
        challenges: Challenges,
        audit: Audit,
    ) -> None:
        self._settings = settings
        self._identity = identity
        self._store = store
        self._index = index
        self._challenges = challenges
        self._audit = audit

    def create_project(self, caller: Caller, name: str, repository: str, server_url: str) -> dict[str, Any]:
        check_name("Repository name", repository)
        project = self._identity.create_project(caller, name)
        self._identity.add_repository(caller, project.project_id, repository)
        return {
            "project_id": project.project_id,
            "name": project.name,
            "settings": self.settings_for(project.project_id, repository),
            "files": self.connection_files(server_url, project.project_id, project.name, repository),
            "next": "Write the files for the coding agents this team uses, creating or merging each as its `how` "
            "says and keeping anything already there, then ask the member to commit them. Each member sets their "
            "personal token once in the SHARED_MEMORY_TOKEN environment variable. Other repositories of the same "
            "product use the same project ID with their own repository name.",
        }

    def settings_for(self, project_id: str, repository: str) -> dict[str, Any]:
        """What one repository commits into .claude/settings.json to connect its Claude Code sessions to a project."""
        return claude_settings(self._settings.plugin_marketplace, project_id, repository)

    def connection_files(
        self, server_url: str, project_id: str, project_name: str, repository: str
    ) -> list[dict[str, Any]]:
        """Every file that connects one repository to its project, for each coding agent."""
        return connection_kit(
            server_url=self._settings.console_url or server_url,
            marketplace=self._settings.plugin_marketplace,
            project_id=project_id,
            project_name=project_name,
            repository=repository,
        )

    def remember(
        self,
        caller: Caller,
        title: str,
        summary: str,
        type: str,
        body: str,
        related_files: list[str] | None = None,
        topic: str | None = None,
    ) -> dict[str, Any]:
        project = caller.require_project()
        memory = Memory(
            title=title.strip(),
            summary=summary.strip(),
            type=type,
            author=caller.member_id,
            body=body,
            related_files=list(related_files or []),
        )
        validate(memory, self._settings.memory_word_limit)
        folder = level_folder("personal", type, project.project_id, caller.member_id)
        if topic is not None:
            topic_folder = slugify(topic)
            if not topic.strip() or topic_folder in ("memory", "index"):
                raise Refused("A topic needs a name made of letters or digits.")
            folder = folder / topic_folder
        with self._store.change(caller.team, committer(caller), f"Remember: {memory.title}") as change:
            path = change.new_path(folder, memory.title)
            change.write(path, memory)
        self._audit.memory(caller, MEMORY_SAVED, str(path), type=memory.type)
        return {"path": str(path)}

    def read(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        memory = describe(location.path, self._store.read(caller.team, location.path))
        memory["pending"] = self._challenges.pending(caller.team, [memory["path"]])[memory["path"]]
        memory["open_challenges"] = self._challenges.against(caller.team, memory["path"])
        return memory

    def history(self, caller: Caller, path: str) -> dict[str, Any]:
        """Every version of one memory, newest first."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        self._store.read(caller.team, location.path)  # refuses a memory that isn't there
        versions = self._store.history(caller.team, location.path)
        return {
            "path": str(location.path),
            "versions": [
                {
                    "commit": version.commit,
                    "at": version.at.isoformat(),
                    "author": version.author,
                    "name": version.name,
                    "message": version.message,
                    "agent": version.agent,
                }
                for version in versions
            ],
        }

    def version(self, caller: Caller, path: str, commit: str) -> dict[str, Any]:
        """One memory as it was at one version."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        return {"path": str(location.path), "commit": commit, "text": self._store.version(caller.team, location.path, commit)}

    def difference(self, caller: Caller, path: str, before: str, after: str) -> dict[str, Any]:
        """What changed in one memory between two versions."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        return {
            "path": str(location.path),
            "before": before,
            "after": after,
            "difference": self._store.difference(caller.team, location.path, before, after),
        }

    def list_folder(self, caller: Caller, folder: str) -> dict[str, Any]:
        caller.require_project()
        caller.require_reach(folder)
        pure = PurePosixPath(folder.replace("\\", "/").strip("/"))
        memories, folders = self._store.list_folder(caller.team, pure)
        pending = self._challenges.pending(caller.team, [str(path) for path, _ in memories])
        return {
            "folder": str(pure),
            "memories": [
                {
                    "path": str(path),
                    "title": m.title,
                    "summary": m.summary,
                    "type": m.type,
                    "status": m.status,
                    "author": m.author,
                    "pending": pending[str(path)],
                }
                for path, m in memories
            ],
            # Listing the projects folder names every project; a restricted one stays out of sight.
            "folders": [str(sub) for sub in folders if project_in(str(sub)) not in caller.unreachable],
        }

    def tree(self, caller: Caller, level: str | None = None) -> dict[str, Any]:
        project = caller.require_project()
        project_folder = PurePosixPath("projects", project.project_id)
        roots = {
            None: [PurePosixPath("team"), project_folder],
            "team": [PurePosixPath("team")],
            "project": [project_folder / "shared"],
            "personal": [project_folder / "people"],
        }
        if level not in roots:
            raise Refused(f"Unknown level {level!r}: use team, project or personal, or leave it out for everything.")
        walked = [
            (folder, memories)
            for root in roots[level]
            for folder, memories in self._store.walk(caller.team, root)
            if memories
        ]
        pending = self._challenges.pending(caller.team, [str(path) for _, memories in walked for path, _ in memories])
        entries = [
            {
                "folder": str(folder),
                "memories": [
                    {"path": str(path), "title": m.title, "summary": m.summary, "pending": pending[str(path)]}
                    for path, m in memories
                ],
            }
            for folder, memories in walked
        ]
        return {"folders": entries}

    def search(
        self, caller: Caller, query: str, level: str | None = None, type: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        project = caller.require_project()
        if level not in (None, "team", "project", "personal"):
            raise Refused(f"Unknown level {level!r}: use team, project or personal.")
        if not query.strip():
            raise Refused("Search needs some words to look for.")
        hits = self._index.search(
            caller.team,
            query,
            project_id=project.project_id,
            levels=None if level is None else [level],
            type=type,
            limit=max(1, min(limit, 50)),
        )
        return {"results": self._found(caller, hits)}

    def search_everywhere(
        self, caller: Caller, query: str, level: str | None = None, type: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Search team memory and every project this member can reach, for the console."""
        if level not in (None, "team", "project", "personal"):
            raise Refused(f"Unknown level {level!r}: use team, project or personal.")
        if not query.strip():
            raise Refused("Search needs some words to look for.")
        hits = self._index.search(
            caller.team,
            query,
            project_id=[project.project_id for project in self._identity.projects(caller.member)],
            levels=None if level is None else [level],
            type=type,
            limit=max(1, min(limit, 50)),
        )
        return {"results": self._found(caller, hits)}

    def _found(self, caller: Caller, hits: list[Hit]) -> list[dict[str, Any]]:
        """Search hits as the memories they came from, with the heading of the section that matched."""
        pending = self._challenges.pending(caller.team, [hit.path for hit in hits])
        results = []
        for hit in hits:
            try:
                memory = self._store.read(caller.team, PurePosixPath(hit.path))
            except Refused:
                continue
            sections = split_sections(memory)
            results.append(
                {
                    "path": hit.path,
                    "title": memory.title,
                    "heading": sections[hit.section_no][0] if hit.section_no < len(sections) else memory.title,
                    "level": hit.level,
                    "type": hit.type,
                    "author": hit.author,
                    "summary": memory.summary,
                    "label": label(caller, hit.level, hit.member_id),
                    "pending": pending[hit.path],
                }
            )
        return results

    def source(self, caller: Caller, path: str) -> str:
        """One memory's file exactly as it is on disk, header and all: what every Claude reads."""
        caller.require_reach(path)
        return self._store.text(caller.team, locate(path).path)

    def explore(self, caller: Caller, folder: str, deep: bool = False) -> dict[str, Any]:
        """One folder of the team's memory for the console's explorer.

        The top holds team memory and every project this member can reach. Each subfolder says how many memories it
        holds and when they last changed, so the structure reads without opening it. Asked for deep, it also sets out
        every folder beneath it with the memories in each, so a whole part of the contents reads on one page.
        """
        pure = PurePosixPath(folder.replace("\\", "/").strip("/"))
        caller.require_reach(str(pure))
        reachable = {project.project_id: project.name for project in self._identity.projects(caller.member)}
        people = {one["employee_id"]: one["name"] for one in self._identity.members(caller.member)}
        memories: list[tuple[PurePosixPath, Memory]] = []
        if not pure.parts:
            subfolders = [PurePosixPath("team")] + [PurePosixPath("projects", project) for project in reachable]
        elif pure.parts == ("projects",):
            subfolders = [PurePosixPath("projects", project) for project in reachable]
        else:
            memories, subfolders = self._store.list_folder(caller.team, pure)
            subfolders = sorted(
                (sub for sub in subfolders if project_in(str(sub)) not in caller.unreachable), key=_accepted_first
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
                        "name": _folder_name(below, reachable, people),
                        "kind": _folder_kind(below),
                        "depth": len(below.parts) - len(pure.parts),
                        "count": count,
                        "changed": changed,
                        "memories": self._entries(caller, held, people),
                    }
                )
        inside.sort(key=lambda section: _accepted_first(PurePosixPath(str(section["path"]))))
        folders = []
        for sub in subfolders:
            count, changed = self._store.extent(caller.team, sub)
            folders.append(
                {
                    "path": str(sub),
                    "name": _folder_name(sub, reachable, people),
                    "kind": _folder_kind(sub),
                    "memories": count,
                    "changed": changed,
                }
            )
        return {
            "folder": str(pure) if pure.parts else "",
            "name": _folder_name(pure, reachable, people) if pure.parts else "Memory",
            "kind": _folder_kind(pure) if pure.parts else "root",
            "trail": [
                {"path": str(PurePosixPath(*pure.parts[:depth])), "name": _folder_name(PurePosixPath(*pure.parts[:depth]), reachable, people)}
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
                "challenged": len(self._challenges.against(caller.team, str(path))),
                "waiting": bool(pending[str(path)]),
            }
            for path, memory in memories
        ]

    def _own_personal_memory(self, caller: Caller, path: str, verb: str) -> tuple[Location, Memory]:
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        memory = self._store.read(caller.team, location.path)
        if location.level != "personal" or location.member_id != caller.member_id:
            raise Refused(
                f"You can only {verb} your own personal memory. Project and team memory change only by "
                "promoting a memory that supersedes it."
            )
        return location, memory

    def edit_memory(
        self,
        caller: Caller,
        path: str,
        title: str | None = None,
        summary: str | None = None,
        type: str | None = None,
        body: str | None = None,
        related_files: list[str] | None = None,
    ) -> dict[str, Any]:
        location, memory = self._own_personal_memory(caller, path, "edit")
        if type is not None and type != location.type:
            raise Refused(
                f"This memory is in the {location.type} folder, so its type must match. To change its type, "
                "remember it again with the new type and delete this one."
            )
        edited = replace(
            memory,
            title=memory.title if title is None else title.strip(),
            summary=memory.summary if summary is None else summary.strip(),
            body=memory.body if body is None else body,
            related_files=memory.related_files if related_files is None else list(related_files),
        )
        validate(edited, self._settings.memory_word_limit)
        with self._store.change(caller.team, committer(caller), f"Edit: {edited.title}") as change:
            change.write(location.path, edited)
        self._audit.memory(caller, MEMORY_EDITED, str(location.path))
        return describe(location.path, edited)

    def delete_memory(self, caller: Caller, path: str) -> dict[str, Any]:
        location, memory = self._own_personal_memory(caller, path, "delete")
        with self._store.change(caller.team, committer(caller), f"Delete: {memory.title}") as change:
            change.delete(location.path)
        self._audit.memory(caller, MEMORY_DELETED, str(location.path))
        return {"deleted": str(location.path)}
