"""What a member's session can do with memory, and the rules that apply."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from shared_memory.config import Settings
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, check_name
from shared_memory.index import SearchIndex
from shared_memory.memory import Location, Memory, locate, personal_folder, slugify
from shared_memory.store import Committer, MemoryStore
from shared_memory.validation import validate


def committer(caller: Caller) -> Committer:
    return Committer(caller.member.member_id, caller.member.name)


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
    if member_id == caller.member.member_id:
        return "your personal memory"
    return f"personal memory of {member_id}, not accepted by the team"


class MemoryService:
    def __init__(self, settings: Settings, identity: Identity, store: MemoryStore, index: SearchIndex) -> None:
        self._settings = settings
        self._identity = identity
        self._store = store
        self._index = index

    def create_project(self, caller: Caller, name: str, repository: str) -> dict[str, Any]:
        check_name("Repository name", repository)
        project = self._identity.create_project(caller, name)
        return {
            "project_id": project.project_id,
            "name": project.name,
            "settings": {"env": {"SHARED_MEMORY_PROJECT": project.project_id, "SHARED_MEMORY_REPOSITORY": repository}},
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
            author=caller.member.member_id,
            body=body,
            related_files=list(related_files or []),
        )
        validate(memory, self._settings.memory_word_limit)
        folder = personal_folder(project.project_id, caller.member.member_id, type)
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
        location = locate(path)
        return describe(location.path, self._store.read(caller.team, location.path))

    def list_folder(self, caller: Caller, folder: str) -> dict[str, Any]:
        pure = PurePosixPath(folder.replace("\\", "/").strip("/"))
        memories, folders = self._store.list_folder(caller.team, pure)
        return {
            "folder": str(pure),
            "memories": [
                {"path": str(path), "title": m.title, "summary": m.summary, "type": m.type, "status": m.status, "author": m.author}
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
        entries = [
            {
                "folder": str(folder),
                "memories": [{"path": str(path), "title": m.title, "summary": m.summary} for path, m in memories],
            }
            for root in roots[level]
            for folder, memories in self._store.walk(caller.team, root)
            if memories
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
        results = []
        for hit in hits:
            try:
                memory = self._store.read(caller.team, PurePosixPath(hit.path))
            except Refused:
                continue
            results.append(
                {
                    "path": hit.path,
                    "title": memory.title,
                    "heading": hit.heading,
                    "level": hit.level,
                    "type": hit.type,
                    "author": hit.author,
                    "summary": memory.summary,
                    "label": label(caller, hit.level, hit.member_id),
                }
            )
        return {"results": results}

    def _own_personal_memory(self, caller: Caller, path: str, verb: str) -> tuple[Location, Memory]:
        location = locate(path)
        memory = self._store.read(caller.team, location.path)
        if location.level != "personal" or location.member_id != caller.member.member_id:
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
