"""What a member's session can do with memory, and the rules that apply."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from shared_memory.audit import MEMORY_DELETED, MEMORY_EDITED, MEMORY_SAVED, Audit
from shared_memory.challenges import Challenges, InDoubt, ranked
from shared_memory.config import Settings
from shared_memory.connection import claude_settings, connection_kit
from shared_memory.departments import Departments
from shared_memory.embeddings import QuerySource
from shared_memory.errors import Refused
from shared_memory.history import MemoryHistory
from shared_memory.identity import Caller, Identity, check_name
from shared_memory.index import Hit, Reach, SearchIndex, split_sections
from shared_memory.memory import (
    COMPANY_FOLDER,
    DEPARTMENTS_FOLDER,
    KNOWN_ISSUE,
    Area,
    Location,
    Memory,
    area_of,
    level_folder,
    locate,
    slugify,
)
from shared_memory.suspected import answer_for, reasons_for
from shared_memory.store import Change, Committer, MemoryStore
from shared_memory.tied import Tie, TiedFiles, file_named
from shared_memory.uses import Uses
from shared_memory.validation import as_written, validate, validate_tied_files, without_hidden


def _promoting(path: str) -> str:
    """What to do with a memory that has just been saved, which is always personal memory at first.

    It goes in the result rather than only in the server's instructions or the skill, because it is the moment the
    choice of level is actually in front of an agent, and because some agents read neither.
    """
    return (
        f"Saved as this member's personal memory: the company can read it but hasn't accepted it. If everyone on this "
        f"project should follow it, promote it with promote(path='{path}', level='project'); level 'department' if it "
        f"is a way of working for every project in this project's department (a department lead promotes there); "
        f"level 'company' if it is policy for every project in the company. Leave it personal if it is only this "
        f"member's own note."
    )


# The most similar memories a save names.
SAVE_SIMILAR_LIMIT = 3


@dataclass(frozen=True)
class SimilarMemory:
    """A memory within the saving member's reach that a save found similar to the memory it saved."""

    path: str
    level: str
    title: str
    summary: str
    similarity: float
    in_doubt: InDoubt | None = None

    def answer(self) -> dict[str, Any]:
        """As the save's answer names it, with the in-doubt line if it is in doubt."""
        answered: dict[str, Any] = {
            "path": self.path,
            "level": self.level,
            "title": self.title,
            "summary": self.summary,
            "similarity": round(self.similarity, 3),
        }
        if self.in_doubt is not None:
            answered["in_doubt"] = self.in_doubt.line()
        return answered


@dataclass(frozen=True)
class TiedMemory:
    """A memory within a session's reach tied to the file it asked about."""

    tie: Tie
    level: str
    memory: Memory

    def answer(self, in_doubt: InDoubt | None) -> dict[str, Any]:
        """As `tied_memories` gives it, with the in-doubt line if it is in doubt."""
        answered: dict[str, Any] = {
            "path": self.tie.memory_path,
            "level": self.level,
            "tied_file": self.tie.tied_file,
            "title": self.memory.title,
            "summary": self.memory.summary,
            "body": self.memory.body,
        }
        if in_doubt is not None:
            answered["in_doubt"] = in_doubt.line()
        return answered


def _resolving(similar: list[SimilarMemory]) -> str:
    """What to do about the similar memories a save named."""
    return (
        f"`similar` names {len(similar)} similar memor{'y' if len(similar) == 1 else 'ies'} in reach. Judge each with "
        "the member: supersede it if this one replaces it, promote this one if the company should follow it, or leave "
        "both if both hold."
    )


def _areas_of(path: str) -> list[Area]:
    """The area of the memory a save changes, declared before its turn. A path that is no memory's changes nothing:
    the save refuses it inside, before writing anything, so it takes no turn."""
    try:
        area = area_of(locate(path).path)
    except Refused:
        return []
    return [area] if area is not None else []


def _edited(
    memory: Memory, title: str | None, summary: str | None, body: str | None, tied_files: list[str] | None
) -> Memory:
    """A memory with an edit's new text. What the edit leaves as it was loses any hidden character saved before the
    server refused them, so only what the member writes now is refused for one."""
    return replace(
        memory,
        title=without_hidden(memory.title) if title is None else title.strip(),
        summary=without_hidden(memory.summary) if summary is None else summary.strip(),
        body=without_hidden(memory.body) if body is None else as_written(body),
        tied_files=[without_hidden(one) for one in memory.tied_files] if tied_files is None else list(tied_files),
    )


def committer(caller: Caller) -> Committer:
    return Committer(caller.member_id, caller.member.name, caller.agent)


def describe(path: PurePosixPath, memory: Memory) -> dict[str, Any]:
    location = locate(str(path))
    return {
        "path": str(path),
        "level": location.level,
        "project_id": location.project_id,
        "foundation": location.foundation,
        "title": memory.title,
        "summary": memory.summary,
        "type": memory.type,
        "author": memory.author,
        "status": memory.status,
        "replaces": memory.replaces,
        "superseded_by": memory.superseded_by,
        "exception_to": memory.exception_to,
        "exception_reason": memory.exception_reason,
        "tied_files": memory.tied_files,
        "promoted_by": memory.promoted_by,
        "imported_by": memory.imported_by,
        "imported_from": memory.imported_from,
        "body": memory.body,
    }


def label(caller: Caller, level: str, member_id: str | None) -> str:
    if level == "company":
        return "company memory"
    if level == "department":
        return "department memory"
    if level == "project":
        return "project memory"
    if member_id == caller.member_id:
        return "your personal memory"
    return f"personal memory of {member_id}, not accepted by the company"


def _known_level(level: str | None) -> None:
    if level not in (None, "company", "department", "project", "personal"):
        raise Refused(f"Unknown level {level!r}: use company, department, project or personal.")


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
        uses: Uses,
        tied: TiedFiles,
        departments: Departments,
    ) -> None:
        self._settings = settings
        self._departments = departments
        self._tied = tied
        self._uses = uses
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
            "next": "Write the files for the coding agents this company uses, creating or merging each as its `how` "
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
        tied_files: list[str] | None = None,
        topic: str | None = None,
    ) -> dict[str, Any]:
        project = caller.require_project()
        if type == KNOWN_ISSUE:
            raise Refused(
                "A known issue goes straight into project memory, never personal memory: save it with save_known_issue."
            )
        memory = Memory(
            title=title.strip(),
            summary=summary.strip(),
            type=type,
            author=caller.member_id,
            body=as_written(body),
            tied_files=list(tied_files or []),
        )
        validate(memory, self._settings.memory_word_limit)
        folder = level_folder("personal", type, project.project_id, caller.member_id)
        if topic is not None:
            topic_folder = slugify(topic)
            if not topic.strip() or topic_folder in ("memory", "index"):
                raise Refused("A topic needs a name made of letters or digits.")
            folder = folder / topic_folder
        self._index.prepare(caller.company, memory)
        mine = Area("personal", project.project_id, caller.member_id)
        with self._store.change(caller.company, committer(caller), f"Remember: {memory.title}", areas=[mine]) as change:
            path = change.new_path(folder, memory.title)
            change.write(path, memory)
            change.also(lambda: self._audit.memory(caller, MEMORY_SAVED, str(path), type=memory.type))
        saved: dict[str, Any] = {"path": str(path), "level": "personal", "next": _promoting(str(path))}
        if similar := self.similar_on_save(caller, path, memory):
            saved["similar"] = [each.answer() for each in similar]
            saved["next"] += " " + _resolving(similar)
        if reasons := reasons_for(memory):
            saved.update(answer_for(reasons))
        return saved

    def similar_on_save(self, caller: Caller, path: PurePosixPath, memory: Memory) -> list[SimilarMemory]:
        """The memories within the caller's reach most similar to one they have just saved. It runs once the save's
        turn is over, and the saved memory's vectors are stored by then, so no model runs (ADR-0012, ADR-0013)."""
        project = caller.require_project()
        close = self._index.similar_to(
            caller.company,
            memory,
            reach=Reach.of_member(
                caller.member_id, project.project_id, caller.unreachable, caller.unreachable_departments
            ),
            threshold=self._settings.save_similar_threshold,
            excluding=path,
        )
        similar: list[SimilarMemory] = []
        for found, similarity in close:
            try:
                other = self._store.read(caller.company, PurePosixPath(found))
            except Refused:
                continue  # moved or deleted since the index was read
            similar.append(SimilarMemory(found, locate(found).level, other.title, other.summary, similarity))
            if len(similar) == SAVE_SIMILAR_LIMIT:
                break
        in_doubt = self._challenges.in_doubt(caller.company, [each.path for each in similar])
        return [replace(each, in_doubt=in_doubt.get(each.path)) for each in similar]

    def read(self, caller: Caller, path: str, for_agent: bool = False) -> dict[str, Any]:
        """One memory in full, with its challenges. For a coding agent, a memory in doubt carries its in-doubt line."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        memory = describe(location.path, self._store.read(caller.company, location.path))
        memory["pending"] = self._challenges.pending(caller.company, [memory["path"]])[memory["path"]]
        memory["open_challenges"] = self._challenges.against(caller, memory["path"])
        memory["possibly_outdated"] = bool(self._uses.possibly_outdated(caller.company, {memory["path"]: memory["status"]}))
        if memory["possibly_outdated"]:
            memory["check"] = self._uses.check(caller.company, memory["path"])
        if for_agent and (in_doubt := self._challenges.in_doubt(caller.company, [memory["path"]]).get(memory["path"])):
            memory["in_doubt"] = in_doubt.line()
        return memory

    def tied_memories(self, caller: Caller, file: str) -> dict[str, Any]:
        """The memories tied to one file, written repository:path, within recall's reach: their own personal memory in
        this project, this project's memory and company memory. A memory in doubt carries its in-doubt line."""
        project = caller.require_project()
        asked = file_named(file)
        reach = Reach.of_recall(caller.member_id, project.project_id, self.department_of(project.project_id))
        ties = self._tied.tied_to(caller.company, asked.repository, [asked.path], reach)
        found: list[TiedMemory] = []
        for tie in ties:
            try:
                memory = self._store.read(caller.company, PurePosixPath(tie.memory_path))
            except Refused:
                continue  # moved or deleted since the index was read
            found.append(TiedMemory(tie, locate(tie.memory_path).level, memory))
        in_doubt = self._challenges.in_doubt(caller.company, [each.tie.memory_path for each in found])
        return {
            "file": asked.written,
            "memories": [each.answer(in_doubt.get(each.tie.memory_path)) for each in found],
        }

    def history(self, caller: Caller, path: str) -> dict[str, Any]:
        """Every version of one memory, newest first."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        self._store.read(caller.company, location.path)  # refuses a memory that isn't there
        versions = self._history.versions(caller.company, location.path, caller.reaches)
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
            "text": self._history.text_at(caller.company, location.path, commit, caller.reaches),
        }

    def list_folder(self, caller: Caller, folder: str) -> dict[str, Any]:
        caller.require_project()
        caller.require_reach(folder)
        pure = PurePosixPath(folder.replace("\\", "/").strip("/"))
        memories, folders = self._store.list_folder(caller.company, pure)
        pending = self._challenges.pending(caller.company, [str(path) for path, _ in memories])
        return {
            "folder": str(pure),
            "memories": [
                {
                    "path": str(path),
                    "title": m.title,
                    "summary": m.summary,
                    "type": m.type,
                    "foundation": locate(str(path)).foundation,
                    "status": m.status,
                    "author": m.author,
                    "pending": pending[str(path)],
                }
                for path, m in memories
            ],
            # Listing the projects or departments folder names every one; a restricted one stays out of sight.
            "folders": [str(sub) for sub in folders if caller.reaches(str(sub))],
        }

    def department_of(self, project_id: str) -> str | None:
        """The department ID of the department a project is in, or None for a project in none."""
        found = self._departments.of_project(project_id)
        return None if found is None else found.department_id

    def department_memory(self, caller: Caller, department_id: str) -> list[str]:
        """The paths of a department's active department memory, for retiring it when the department is removed."""
        return [
            str(path)
            for _, memories in self._store.walk(caller.company, PurePosixPath(DEPARTMENTS_FOLDER, department_id))
            for path, memory in memories
            if memory.status == "active"
        ]

    def tree(self, caller: Caller, level: str | None = None) -> dict[str, Any]:
        project = caller.require_project()
        project_folder = PurePosixPath("projects", project.project_id)
        department_id = self.department_of(project.project_id)
        department = [] if department_id is None else [PurePosixPath(DEPARTMENTS_FOLDER, department_id)]
        roots = {
            None: [PurePosixPath(COMPANY_FOLDER), *department, project_folder],
            "company": [PurePosixPath(COMPANY_FOLDER)],
            "department": department,
            "project": [project_folder / "shared"],
            "personal": [project_folder / "people"],
        }
        if level not in roots:
            raise Refused(
                f"Unknown level {level!r}: use company, department, project or personal, or leave it out for everything."
            )
        walked = [
            (folder, memories)
            for root in roots[level]
            for folder, memories in self._store.walk(caller.company, root)
            if memories
        ]
        pending = self._challenges.pending(caller.company, [str(path) for _, memories in walked for path, _ in memories])
        entries = [
            {
                "folder": str(folder),
                "memories": [
                    {
                        "path": str(path),
                        "title": m.title,
                        "summary": m.summary,
                        "foundation": locate(str(path)).foundation,
                        "pending": pending[str(path)],
                    }
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
        _known_level(level)
        if not query.strip():
            raise Refused("Search needs some words to look for.")
        department_id = self.department_of(project.project_id)
        candidates = self._index.search(
            caller.company,
            query,
            project_id=project.project_id,
            departments=[] if department_id is None else [department_id],
            levels=None if level is None else [level],
            type=type,
            limit=None,
            source=QuerySource.SEARCH,
        )
        # Every candidate is ranked again before the cut, so a memory in doubt makes way for one that isn't.
        in_doubt = self._challenges.in_doubt(caller.company, [hit.path for hit in candidates])
        penalty = self._settings.in_doubt_penalty
        hits = sorted(candidates, key=lambda hit: -ranked(hit.score, in_doubt.get(hit.path), penalty))
        results = self._found(caller, hits[: max(1, min(limit, 50))], in_doubt=in_doubt)
        if any(result["possibly_outdated"] for result in results):
            return {"results": results, "check": self._uses.check_any()}
        return {"results": results}

    def search_everywhere(
        self, caller: Caller, query: str, level: str | None = None, type: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Search company memory, every project this member can reach and the department memory of those projects'
        departments, for the console."""
        _known_level(level)
        if not query.strip():
            raise Refused("Search needs some words to look for.")
        projects = [project.project_id for project in self._identity.projects(caller.member)]
        hits = self._index.search(
            caller.company,
            query,
            project_id=projects,
            departments=sorted({found.department_id for found in self._departments.of_projects(projects).values()}),
            levels=None if level is None else [level],
            type=type,
            limit=max(1, min(limit, 50)),
            source=QuerySource.CONSOLE_SEARCH,
        )
        return {"results": self._found(caller, hits)}

    def _found(
        self, caller: Caller, hits: list[Hit], in_doubt: dict[str, InDoubt] | None = None
    ) -> list[dict[str, Any]]:
        """Search hits as the memories they came from, with the heading of the section that matched. For a coding
        agent, which passes which of them are in doubt, each also says whether it is possibly outdated and, if it is
        in doubt, carries its in-doubt line; the console's search page shows neither. For the console, each says
        whether it matched the words searched for, so a match by meaning alone can be set apart."""
        for_agent = in_doubt is not None
        pending = self._challenges.pending(caller.company, [hit.path for hit in hits])
        found: list[tuple[Hit, Memory]] = []
        for hit in hits:
            try:
                found.append((hit, self._store.read(caller.company, PurePosixPath(hit.path))))
            except Refused:
                continue
        outdated = (
            self._uses.possibly_outdated(caller.company, {hit.path: memory.status for hit, memory in found})
            if for_agent
            else set()
        )
        results = []
        for hit, memory in found:
            sections = split_sections(memory)
            results.append(
                {
                    "path": hit.path,
                    "title": memory.title,
                    "heading": sections[hit.section_no][0] if hit.section_no < len(sections) else memory.title,
                    "level": hit.level,
                    "type": hit.type,
                    "foundation": locate(hit.path).foundation,
                    "author": hit.author,
                    "summary": memory.summary,
                    "label": label(caller, hit.level, hit.member_id),
                    "pending": pending[hit.path],
                    "possibly_outdated": hit.path in outdated,
                    **({} if for_agent else {"words_match": hit.words_match}),
                    **({"in_doubt": doubt.line()} if in_doubt and (doubt := in_doubt.get(hit.path)) else {}),
                }
            )
        return results

    def source(self, caller: Caller, path: str) -> str:
        """One memory's file exactly as it is on disk, header and all: what every Claude reads."""
        caller.require_reach(path)
        return self._store.text(caller.company, locate(path).path)

    def _own_personal_memory(self, caller: Caller, change: Change, path: str, verb: str) -> tuple[Location, Memory]:
        """The caller's own personal memory, read in the save that changes it."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        memory = change.read(location.path)
        if location.level != "personal" or location.member_id != caller.member_id:
            raise Refused(
                f"You can only {verb} your own personal memory. Project and company memory change only by "
                "promoting a memory that supersedes it."
            )
        # A memory offered in a challenge stays as offered, so whoever decides it accepts the text they read.
        if waiting := self._challenges.open_challenges(caller.company, challenger_paths=[str(location.path)]):
            raise Refused(f"This memory is waiting on challenge {waiting[0].id}. Wait for it to be decided.")
        return location, memory

    def _prepare_edit(
        self,
        caller: Caller,
        path: str,
        title: str | None,
        summary: str | None,
        body: str | None,
        tied_files: list[str] | None,
    ) -> None:
        """Embed an edit's new text before its save takes its turn, only once the edit would be allowed: an edit that
        will be refused embeds nothing. The refusal itself is left for the save to raise."""
        try:
            caller.require_project()
            caller.require_reach(path)
            location = locate(path)
            if location.level != "personal" or location.member_id != caller.member_id:
                return
            memory = self._store.read(caller.company, location.path)
            edited = _edited(memory, title, summary, body, tied_files)
            validate(edited, self._settings.memory_word_limit)
        except Refused:
            return
        self._index.prepare(caller.company, edited)

    def edit_memory(
        self,
        caller: Caller,
        path: str,
        title: str | None = None,
        summary: str | None = None,
        type: str | None = None,
        body: str | None = None,
        tied_files: list[str] | None = None,
    ) -> dict[str, Any]:
        self._prepare_edit(caller, path, title, summary, body, tied_files)
        with self._store.change(caller.company, committer(caller), areas=_areas_of(path)) as change:
            location, memory = self._own_personal_memory(caller, change, path, "edit")
            if type is not None and type != location.type:
                raise Refused(
                    f"This memory is in the {location.type} folder, so its type must match. To change its type, "
                    "remember it again with the new type and delete this one."
                )
            edited = _edited(memory, title, summary, body, tied_files)
            validate(edited, self._settings.memory_word_limit)
            change.message = f"Edit: {edited.title}"
            change.write(location.path, edited)
            change.also(lambda: self._audit.memory(caller, MEMORY_EDITED, str(location.path)))
        self._challenges.resolve_doubts(caller.company, str(location.path), caller.member_id, "its author edited it.")
        described = describe(location.path, edited)
        if reasons := reasons_for(edited):
            described.update(answer_for(reasons))
        return described

    def tie(self, caller: Caller, path: str, tied_files: list[str]) -> dict[str, Any]:
        """Replace the tied files of the caller's own personal memory. Whether project and company memory may be retied
        too is undecided (#503), so until then they are retied by superseding them."""
        validate_tied_files(tied_files)
        with self._store.change(caller.company, committer(caller), areas=_areas_of(path)) as change:
            location, memory = self._own_personal_memory(caller, change, path, "tie")
            tied = replace(memory, tied_files=list(tied_files))
            change.message = f"Tie: {tied.title}"
            change.write(location.path, tied)
            change.also(lambda: self._audit.memory(caller, MEMORY_EDITED, str(location.path)))
        return describe(location.path, tied)

    def delete_memory(self, caller: Caller, path: str) -> dict[str, Any]:
        with self._store.change(caller.company, committer(caller), areas=_areas_of(path)) as change:
            location, memory = self._own_personal_memory(caller, change, path, "delete")
            change.message = f"Delete: {memory.title}"
            change.delete(location.path)
            change.also(lambda: self._audit.memory(caller, MEMORY_DELETED, str(location.path)))
        return {"deleted": str(location.path)}
