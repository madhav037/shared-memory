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
from shared_memory.history import MemoryHistory
from shared_memory.identity import Caller, Identity, check_name, project_in
from shared_memory.index import Hit, SearchIndex, split_sections
from shared_memory.memory import Location, Memory, level_folder, locate, slugify
from shared_memory.store import Change, Committer, MemoryStore
from shared_memory.validation import validate


def _promoting(path: str) -> str:
    """What to do with a memory that has just been saved, which is always personal memory at first.

    It goes in the result rather than only in the server's instructions or the skill, because it is the moment the
    choice of level is actually in front of an agent, and because some agents read neither.
    """
    return (
        f"Saved as this member's personal memory: the team can read it but hasn't accepted it. If everyone on this "
        f"project should follow it, promote it with promote(path='{path}', level='project'), or level 'team' if it "
        f"holds for every project in the team. Anything written for the whole team, such as onboarding or how-we-work "
        f"notes, belongs at one of those levels. Leave it personal if it is only this member's own note."
    )


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
        history: MemoryHistory,
        index: SearchIndex,
        challenges: Challenges,
        audit: Audit,
    ) -> None:
        self._settings = settings
        self._identity = identity
        self._store = store
        self._history = history
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
        return {"path": str(path), "level": "personal", "next": _promoting(str(path))}

    def read(self, caller: Caller, path: str) -> dict[str, Any]:
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        memory = describe(location.path, self._store.read(caller.team, location.path))
        memory["pending"] = self._challenges.pending(caller.team, [memory["path"]])[memory["path"]]
        memory["open_challenges"] = self._challenges.against(caller, memory["path"])
        return memory

    def history(self, caller: Caller, path: str) -> dict[str, Any]:
        """Every version of one memory, newest first."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        self._store.read(caller.team, location.path)  # refuses a memory that isn't there
        versions = self._history.versions(caller.team, location.path)
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
        return {
            "path": str(location.path),
            "commit": commit,
            "text": self._history.text_at(caller.team, location.path, commit),
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

    def _own_personal_memory(self, caller: Caller, change: Change, path: str, verb: str) -> tuple[Location, Memory]:
        """The caller's own personal memory, read in the save that changes it."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        memory = change.read(location.path)
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
        with self._store.change(caller.team, committer(caller)) as change:
            location, memory = self._own_personal_memory(caller, change, path, "edit")
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
            change.message = f"Edit: {edited.title}"
            change.write(location.path, edited)
        self._audit.memory(caller, MEMORY_EDITED, str(location.path))
        return describe(location.path, edited)

    def delete_memory(self, caller: Caller, path: str) -> dict[str, Any]:
        with self._store.change(caller.team, committer(caller)) as change:
            location, memory = self._own_personal_memory(caller, change, path, "delete")
            change.message = f"Delete: {memory.title}"
            change.delete(location.path)
        self._audit.memory(caller, MEMORY_DELETED, str(location.path))
        return {"deleted": str(location.path)}
