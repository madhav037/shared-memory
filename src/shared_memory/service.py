"""What a member's session can do with memory, and the rules that apply."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from shared_memory.challenges import Challenges
from shared_memory.config import Settings
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, check_name
from shared_memory.index import SearchIndex, split_sections
from shared_memory.memory import Location, Memory, level_folder, locate, slugify
from shared_memory.store import Committer, MemoryStore
from shared_memory.validation import validate


def committer(caller: Caller) -> Committer:
    return Committer(caller.member_id, caller.member.name)


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
        self, settings: Settings, identity: Identity, store: MemoryStore, index: SearchIndex, challenges: Challenges
    ) -> None:
        self._settings = settings
        self._identity = identity
        self._store = store
        self._index = index
        self._challenges = challenges

    def create_project(self, caller: Caller, name: str, repository: str) -> dict[str, Any]:
        check_name("Repository name", repository)
        project = self._identity.create_project(caller, name)
        self._identity.add_repository(caller, project.project_id, repository)
        return {
            "project_id": project.project_id,
            "name": project.name,
            "settings": self.settings_for(project.project_id, repository),
            "next": "Merge these settings into this repository's committed .claude/settings.json (keep any existing "
            "keys), then ask the member to commit it. Other repositories of the same product can use the same "
            "project ID with their own repository name.",
        }

    def settings_for(self, project_id: str, repository: str) -> dict[str, Any]:
        """What one repository commits into .claude/settings.json to connect its sessions to a project."""
        return {
            "extraKnownMarketplaces": {
                "shared-memory": {"source": {"source": "github", "repo": self._settings.plugin_marketplace}}
            },
            "enabledPlugins": {"shared-memory@shared-memory": True},
            "env": {"SHARED_MEMORY_PROJECT": project_id, "SHARED_MEMORY_REPOSITORY": repository},
        }

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
        return {"path": str(path)}

    def read(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        location = locate(path)
        memory = describe(location.path, self._store.read(caller.team, location.path))
        memory["pending"] = self._challenges.pending(caller.team, [memory["path"]])[memory["path"]]
        memory["open_challenges"] = self._challenges.against(caller.team, memory["path"])
        return memory

    def history(self, caller: Caller, path: str) -> dict[str, Any]:
        """Every version of one memory, newest first."""
        caller.require_project()
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
                }
                for version in versions
            ],
        }

    def version(self, caller: Caller, path: str, commit: str) -> dict[str, Any]:
        """One memory as it was at one version."""
        caller.require_project()
        location = locate(path)
        return {"path": str(location.path), "commit": commit, "text": self._store.version(caller.team, location.path, commit)}

    def difference(self, caller: Caller, path: str, before: str, after: str) -> dict[str, Any]:
        """What changed in one memory between two versions."""
        caller.require_project()
        location = locate(path)
        return {
            "path": str(location.path),
            "before": before,
            "after": after,
            "difference": self._store.difference(caller.team, location.path, before, after),
        }

    def list_folder(self, caller: Caller, folder: str) -> dict[str, Any]:
        caller.require_project()
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
            "folders": [str(sub) for sub in folders],
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
        return {"results": results}

    def _own_personal_memory(self, caller: Caller, path: str, verb: str) -> tuple[Location, Memory]:
        caller.require_project()
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
        return describe(location.path, edited)

    def delete_memory(self, caller: Caller, path: str) -> dict[str, Any]:
        location, memory = self._own_personal_memory(caller, path, "delete")
        with self._store.change(caller.team, committer(caller), f"Delete: {memory.title}") as change:
            change.delete(location.path)
        return {"deleted": str(location.path)}
