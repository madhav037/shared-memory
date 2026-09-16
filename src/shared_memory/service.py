"""What a member's session can do with memory, and the rules that apply."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from shared_memory.identity import Caller, Identity, check_name
from shared_memory.memory import Memory, locate, personal_folder, type_folder
from shared_memory.store import Committer, MemoryStore


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


class MemoryService:
    def __init__(self, identity: Identity, store: MemoryStore) -> None:
        self._identity = identity
        self._store = store

    def create_project(self, caller: Caller, name: str, repository: str) -> dict[str, Any]:
        check_name("Repository name", repository)
        project = self._identity.create_project(caller, name)
        return {
            "project_id": project.project_id,
            "name": project.name,
            "settings": {"env": {"SHARED_MEMORY_PROJECT": project.project_id, "SHARED_MEMORY_REPOSITORY": repository}},
        }

    def remember(self, caller: Caller, title: str, summary: str, type: str, body: str) -> dict[str, Any]:
        project = caller.require_project()
        folder = personal_folder(project.project_id, caller.member.member_id, type)
        memory = Memory(title=title, summary=summary, type=type, author=caller.member.member_id, body=body)
        type_folder(type)
        with self._store.change(caller.team, committer(caller), f"Remember: {title}") as change:
            path = change.new_path(folder, title)
            change.write(path, memory)
        return {"path": str(path)}

    def read(self, caller: Caller, path: str) -> dict[str, Any]:
        location = locate(path)
        return describe(location.path, self._store.read(caller.team, location.path))
