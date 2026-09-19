"""The console's JSON API.

It is another transport onto the same services the memory tools use, like the hook endpoints. Every call is declared
once, with the shape it answers with: the declarations serve the requests and describe the API, so the console's types
can be generated from that description and can't drift away from it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, date, datetime, time
from typing import Any, Literal
from urllib.parse import quote

import anyio.to_thread
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from shared_memory.audit import (
    ACCESS_GRANTED,
    ACCESS_REVOKED,
    ADMIN_GRANTED,
    ADMIN_REVOKED,
    LEAD_APPOINTED,
    LEAD_REMOVED,
    MEMBER_ADDED,
    MEMBER_CHANGED,
    MEMBER_REMOVED,
    OWNERSHIP_HANDED_OVER,
    PROJECT_CREATED,
    PROJECT_OPENED,
    PROJECT_RENAMED,
    PROJECT_RESTRICTED,
    REPOSITORY_ADDED,
    REPOSITORY_REMOVED,
    TOKEN_ISSUED,
    Audit,
)
from shared_memory.briefing import Briefing, pin_target
from shared_memory.challenges import Challenge, Challenges, project_of
from shared_memory.config import Settings
from shared_memory.console_sessions import COOKIE, ConsoleSessions
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Member
from shared_memory.lifecycle import Lifecycle
from shared_memory.memory import locate
from shared_memory.service import MemoryService

PREFIX = "/api"
CONSOLE_HEADER = "x-shared-memory-console"


def _plainly(wrong: Exception) -> str:
    """A refusal a member can act on, rather than a validation dump."""
    if isinstance(wrong, ValidationError):
        missing = ", ".join(str(problem["loc"][-1]) for problem in wrong.errors())
        return f"That request was missing something: {missing}."
    return "That request wasn't understood."


def _project_in(path: str) -> str | None:
    """The project a memory path belongs to, or nothing for team memory and anything unreadable."""
    try:
        return locate(path).project_id
    except Refused:
        return None


def _may_be_pinned(path: str) -> bool:
    """Whether a folder is a topic, which is the only kind of folder a pin can point at."""
    try:
        pin_target(path)
    except Refused:
        return False
    return True


def _sign_in_first() -> Response:
    return JSONResponse({"message": "Sign in to the console first."}, status_code=401)


def _moment(asked: str | None, edge: time) -> datetime | None:
    """A date filter as a moment: a plain date covers its whole day."""
    if not asked:
        return None
    try:
        return datetime.fromisoformat(asked) if "T" in asked else datetime.combine(date.fromisoformat(asked), edge, UTC)
    except ValueError:
        raise ValueError(f"{asked!r} is not a date") from None


class SignedInMember(BaseModel):
    """Who the console is signed in as."""

    employee_id: str
    name: str
    team: str
    role: Literal["owner", "admin", "member"]
    leads_a_project: bool


class Status(BaseModel):
    """Whether the console has reached the server, and who it is signed in as."""

    signed_in: bool
    github_sign_in: bool
    member: SignedInMember | None


class AuditEvent(BaseModel):
    """One thing that happened, and who did it."""

    id: int
    at: datetime
    actor: str
    kind: str
    project_id: str | None
    target: str | None
    detail: dict[str, Any]


class AuditPage(BaseModel):
    """A page of the audit log, newest first, with where the next page starts."""

    events: list[AuditEvent]
    next: int | None


class ProjectMember(BaseModel):
    """A member named on a project."""

    employee_id: str
    name: str


class ProjectSummary(BaseModel):
    """A project the member can reach, and who looks after it."""

    project_id: str
    name: str
    restricted: bool
    leads: list[ProjectMember]
    you_lead: bool


class Projects(BaseModel):
    projects: list[ProjectSummary]


class ConnectionFile(BaseModel):
    """One file a repository commits to connect a coding agent's sessions to its project."""

    agent: str
    path: str
    action: str
    how: str
    contents: str


class ProjectRepository(BaseModel):
    """A repository of a project, with what it commits to connect its sessions to the project."""

    name: str
    settings: str
    files: list[ConnectionFile]


class ProjectDetail(BaseModel):
    """One project: who leads it, who is allowed in, which repositories belong to it, and what may be changed."""

    project_id: str
    name: str
    restricted: bool
    leads: list[ProjectMember]
    access: list[ProjectMember]
    repositories: list[ProjectRepository]
    you_lead: bool
    you_may_change: bool


class ProjectName(BaseModel):
    """What a project is called."""

    name: str


class Appointment(BaseModel):
    """The member being made a lead of this project."""

    employee_id: str


class RepositoryName(BaseModel):
    """A repository's short name, unique within its project."""

    name: str


class Restriction(BaseModel):
    """Whether this project is closed to its access list, or open to the whole team."""

    restricted: bool


class AccessChange(BaseModel):
    """The member being let into this project."""

    employee_id: str


class PendingChallenge(BaseModel):
    """A challenge this personal memory is waiting on."""

    challenge_id: int
    kind: str
    replaces: str | None


class OpenChallenge(BaseModel):
    """A challenge raised against this memory."""

    challenge_id: int
    kind: str
    raised_by: str
    challenger_path: str | None


class TreeMemory(BaseModel):
    path: str
    title: str
    summary: str
    pinned: bool
    pending: list[PendingChallenge]


class TreeFolder(BaseModel):
    """A folder of memory. A topic folder can be pinned, which pins its index."""

    folder: str
    pinnable: bool
    pinned: bool
    memories: list[TreeMemory]


class Tree(BaseModel):
    """A project's memory, folder by folder."""

    folders: list[TreeFolder]


class Pin(BaseModel):
    """One thing pinned into every session's briefing for this project."""

    path: str
    kind: str
    level: str
    title: str
    tokens: int
    pinned_by: str
    pinned_at: datetime


class Pins(BaseModel):
    """Everything pinned that this project's sessions are briefed with, and how big the briefing may be."""

    pins: list[Pin]
    tokens: int
    cap: int


class PinState(BaseModel):
    """Whether a memory or topic folder is pinned into every briefing it belongs in."""

    path: str
    pinned: bool


class MemoryPath(BaseModel):
    """The memory or topic folder this change is about."""

    path: str


class ChallengedMemory(BaseModel):
    """One side of a challenge: a memory as it stands now."""

    path: str
    title: str
    summary: str
    body: str
    level: str
    type: str
    author: str
    status: str


class ChallengeDetail(BaseModel):
    """A challenge waiting for a decision, with both memories to compare."""

    challenge_id: int
    kind: str
    project_id: str | None
    raised_by: str
    raised_at: datetime
    yours: bool
    target: ChallengedMemory
    challenger: ChallengedMemory | None


class RaisedChallenge(BaseModel):
    """A challenge this member raised, and how it ended."""

    challenge_id: int
    kind: str
    target_path: str
    target_title: str
    challenger_path: str | None
    raised_at: datetime
    state: str
    decided_by: str | None
    decided_at: datetime | None
    explanation: str | None


class ChallengeList(BaseModel):
    """What is waiting for this member's decision, and what they have asked of others."""

    waiting: list[ChallengeDetail]
    raised: list[RaisedChallenge]


class Decision(BaseModel):
    """Accept a challenge or reject it."""

    decision: Literal["accept", "reject"]


class Retired(BaseModel):
    """What retiring did: the memory is retired, or its author has been asked to retire it."""

    status: str
    path: str
    challenge_id: int | None


class MemoryDetail(BaseModel):
    """One memory in full, as its author wrote it."""

    path: str
    level: str
    project_id: str | None
    title: str
    summary: str
    type: str
    author: str
    status: str
    replaces: str | None
    superseded_by: str | None
    exception_to: str | None
    related_files: list[str]
    promoted_by: str | None
    body: str
    author_name: str
    source: str
    pinned: bool
    pending: list[PendingChallenge]
    open_challenges: list[OpenChallenge]


class SearchHit(BaseModel):
    path: str
    project_id: str | None
    title: str
    heading: str
    level: str
    type: str
    author: str
    summary: str
    label: str
    pending: list[PendingChallenge]


class SearchResults(BaseModel):
    results: list[SearchHit]


class FolderEntry(BaseModel):
    """A folder inside the one being looked at, and what it holds."""

    path: str
    name: str
    kind: str
    memories: int
    changed: datetime | None


class FileEntry(BaseModel):
    """A memory in the folder being looked at."""

    path: str
    title: str
    summary: str
    type: str
    level: str
    status: str
    author: str
    author_name: str
    changed: datetime | None
    pinned: bool
    challenged: int
    waiting: bool


class FolderSection(BaseModel):
    """A folder beneath the one being looked at, with the memories directly in it."""

    path: str
    name: str
    kind: str
    depth: int
    count: int
    changed: datetime | None
    memories: list[FileEntry]


class Crumb(BaseModel):
    """A folder on the way down to the one being looked at."""

    path: str
    name: str


class Folder(BaseModel):
    """One folder of the team's memory: where it sits, the folders in it, and its memories."""

    folder: str
    name: str
    kind: str
    pinnable: bool
    pinned: bool
    trail: list[Crumb]
    folders: list[FolderEntry]
    memories: list[FileEntry]
    inside: list[FolderSection]


class MemberSummary(BaseModel):
    """One member of the team, as an admin sees them."""

    employee_id: str
    name: str
    role: Literal["owner", "admin", "member"]
    github_login: str | None
    removed: bool


class Members(BaseModel):
    members: list[MemberSummary]


class NewMember(BaseModel):
    """A member being added to the team."""

    employee_id: str
    name: str
    github: str | None = None


class ChangedMember(BaseModel):
    """What to correct about a member. Anything left out stays as it was."""

    name: str | None = None
    github: str | None = None


class AdminChange(BaseModel):
    """Whether this member should be an admin."""

    admin: bool


class MemoryVersion(BaseModel):
    """One version of a memory in the memory folder's history."""

    commit: str
    at: datetime
    author: str
    name: str
    message: str
    agent: str | None


class MemoryHistory(BaseModel):
    path: str
    versions: list[MemoryVersion]


class MemoryAtVersion(BaseModel):
    """A memory's text as it was at one version."""

    path: str
    commit: str
    text: str


class MemoryDifference(BaseModel):
    """What changed in a memory between two versions."""

    path: str
    before: str
    after: str
    difference: str


class IssuedToken(BaseModel):
    """A personal token, shown the once. The console never shows it again."""

    employee_id: str
    personal_token: str
    server_url: str


@dataclass(frozen=True)
class Declaration:
    """One call the console can make, and what it answers with. A call that answers `None` redirects instead."""

    path: str
    method: str
    operation_id: str
    summary: str
    answers: type[BaseModel] | None
    changes: bool = False
    query: tuple[str, ...] = ()
    accepts: type[BaseModel] | None = None


DECLARATIONS: tuple[Declaration, ...] = (
    Declaration(
        path="/status",
        method="GET",
        operation_id="status",
        summary="Whether the console has reached the server, and who it is signed in as.",
        answers=Status,
    ),
    Declaration(
        path="/sign-in/github",
        method="GET",
        operation_id="sign_in",
        summary="Begin signing in: send the member to GitHub.",
        answers=None,
    ),
    Declaration(
        path="/sign-in/github/callback",
        method="GET",
        operation_id="sign_in_callback",
        summary="Finish signing in and return the member to the console.",
        answers=None,
    ),
    Declaration(
        path="/projects",
        method="GET",
        operation_id="projects",
        summary="The projects this member can reach, with the members who lead each one.",
        answers=Projects,
    ),
    Declaration(
        path="/projects",
        method="POST",
        operation_id="create_project",
        summary="Create a project. Whoever creates it is its first project lead.",
        answers=ProjectDetail,
        changes=True,
        accepts=ProjectName,
    ),
    Declaration(
        path="/projects/{project_id}",
        method="GET",
        operation_id="project",
        summary="One project: its leads, its repositories and the settings each one commits.",
        answers=ProjectDetail,
    ),
    Declaration(
        path="/projects/{project_id}/rename",
        method="POST",
        operation_id="rename_project",
        summary="Change a project's name. Its project ID stays as it is.",
        answers=ProjectDetail,
        changes=True,
        accepts=ProjectName,
    ),
    Declaration(
        path="/projects/{project_id}/leads",
        method="POST",
        operation_id="appoint_lead",
        summary="Make a member a lead of this project.",
        answers=ProjectDetail,
        changes=True,
        accepts=Appointment,
    ),
    Declaration(
        path="/projects/{project_id}/leads/{employee_id}/remove",
        method="POST",
        operation_id="remove_lead",
        summary="Take a lead off this project.",
        answers=ProjectDetail,
        changes=True,
    ),
    Declaration(
        path="/projects/{project_id}/restrict",
        method="POST",
        operation_id="restrict_project",
        summary="Close a project to its access list, or open it to the whole team again.",
        answers=ProjectDetail,
        changes=True,
        accepts=Restriction,
    ),
    Declaration(
        path="/projects/{project_id}/access",
        method="POST",
        operation_id="grant_access",
        summary="Let a member into a restricted project.",
        answers=ProjectDetail,
        changes=True,
        accepts=AccessChange,
    ),
    Declaration(
        path="/projects/{project_id}/access/{employee_id}/remove",
        method="POST",
        operation_id="revoke_access",
        summary="Take a member off a project's access list.",
        answers=ProjectDetail,
        changes=True,
    ),
    Declaration(
        path="/projects/{project_id}/repositories",
        method="POST",
        operation_id="add_repository",
        summary="Add a repository to this project.",
        answers=ProjectDetail,
        changes=True,
        accepts=RepositoryName,
    ),
    Declaration(
        path="/projects/{project_id}/repositories/{repository}/remove",
        method="POST",
        operation_id="remove_repository",
        summary="Forget a repository of this project.",
        answers=ProjectDetail,
        changes=True,
    ),
    Declaration(
        path="/projects/{project_id}/tree",
        method="GET",
        operation_id="tree",
        summary="A project's memory as a folder tree, with each memory's title and summary.",
        answers=Tree,
        query=("level",),
    ),
    Declaration(
        path="/projects/{project_id}/memory",
        method="GET",
        operation_id="memory",
        summary="One memory in full, with any challenges on it.",
        answers=MemoryDetail,
        query=("path",),
    ),
    Declaration(
        path="/projects/{project_id}/search",
        method="GET",
        operation_id="search",
        summary="Memories that match, by meaning and by exact words.",
        answers=SearchResults,
        query=("query", "level", "type", "limit"),
    ),
    Declaration(
        path="/audit",
        method="GET",
        operation_id="audit",
        summary="The team's audit log, newest first.",
        answers=AuditPage,
        query=("limit", "before", "member", "kind", "project", "since", "until"),
    ),
    Declaration(
        path="/projects/{project_id}/pins",
        method="GET",
        operation_id="pins",
        summary="Everything pinned that this project's sessions are briefed with.",
        answers=Pins,
    ),
    Declaration(
        path="/projects/{project_id}/pins",
        method="POST",
        operation_id="pin",
        summary="Pin a project or team memory, or a topic folder, into every session's briefing.",
        answers=Pins,
        changes=True,
        accepts=MemoryPath,
    ),
    Declaration(
        path="/projects/{project_id}/pins/remove",
        method="POST",
        operation_id="unpin",
        summary="Remove a pin, so it no longer appears in the briefing.",
        answers=Pins,
        changes=True,
        accepts=MemoryPath,
    ),
    Declaration(
        path="/files",
        method="GET",
        operation_id="files",
        summary="One folder of the team's memory: its folders, with what they hold, and its memories; deep, everything beneath it.",
        answers=Folder,
        query=("folder", "deep"),
    ),
    Declaration(
        path="/memory",
        method="GET",
        operation_id="memory_at",
        summary="Any memory this member can reach, by its path, with its file exactly as Claude reads it.",
        answers=MemoryDetail,
        query=("path",),
    ),
    Declaration(
        path="/memory/history",
        method="GET",
        operation_id="history_at",
        summary="Every version of a memory, by its path, newest first.",
        answers=MemoryHistory,
        query=("path",),
    ),
    Declaration(
        path="/memory/version",
        method="GET",
        operation_id="version_at",
        summary="A memory, by its path, as it was at one version.",
        answers=MemoryAtVersion,
        query=("path", "commit"),
    ),
    Declaration(
        path="/memory/difference",
        method="GET",
        operation_id="difference_at",
        summary="What changed in a memory, by its path, between two versions.",
        answers=MemoryDifference,
        query=("path", "before", "after"),
    ),
    Declaration(
        path="/memory/pin",
        method="POST",
        operation_id="pin_at",
        summary="Pin a project or team memory, or a topic folder, into every briefing it belongs in.",
        answers=PinState,
        changes=True,
        accepts=MemoryPath,
    ),
    Declaration(
        path="/memory/unpin",
        method="POST",
        operation_id="unpin_at",
        summary="Remove a pin.",
        answers=PinState,
        changes=True,
        accepts=MemoryPath,
    ),
    Declaration(
        path="/memory/retire",
        method="POST",
        operation_id="retire_at",
        summary="Retire a memory that is no longer true; another author's raises a challenge they decide.",
        answers=Retired,
        changes=True,
        accepts=MemoryPath,
    ),
    Declaration(
        path="/search",
        method="GET",
        operation_id="search_everywhere",
        summary="Memories that match, across team memory and every project this member can reach.",
        answers=SearchResults,
        query=("query", "level", "type", "limit"),
    ),
    Declaration(
        path="/challenges",
        method="GET",
        operation_id="challenges",
        summary="Challenges waiting for this member's decision, and the ones they raised.",
        answers=ChallengeList,
    ),
    Declaration(
        path="/challenges/{challenge_id}/decide",
        method="POST",
        operation_id="decide_challenge",
        summary="Accept a challenge or reject it.",
        answers=ChallengeList,
        changes=True,
        accepts=Decision,
    ),
    Declaration(
        path="/projects/{project_id}/retire",
        method="POST",
        operation_id="retire",
        summary="Retire a memory that is no longer true; another author's raises a challenge they decide.",
        answers=Retired,
        changes=True,
        accepts=MemoryPath,
    ),
    Declaration(
        path="/projects/{project_id}/memory/history",
        method="GET",
        operation_id="history",
        summary="Every version of one memory, newest first.",
        answers=MemoryHistory,
        query=("path",),
    ),
    Declaration(
        path="/projects/{project_id}/memory/version",
        method="GET",
        operation_id="version",
        summary="A memory as it was at one version.",
        answers=MemoryAtVersion,
        query=("path", "commit"),
    ),
    Declaration(
        path="/projects/{project_id}/memory/difference",
        method="GET",
        operation_id="difference",
        summary="What changed in a memory between two versions.",
        answers=MemoryDifference,
        query=("path", "before", "after"),
    ),
    Declaration(
        path="/members",
        method="GET",
        operation_id="members",
        summary="Everyone in the team, with their role and GitHub account.",
        answers=Members,
    ),
    Declaration(
        path="/members",
        method="POST",
        operation_id="add_member",
        summary="Add a member and issue their first personal token.",
        answers=IssuedToken,
        changes=True,
        accepts=NewMember,
    ),
    Declaration(
        path="/members/{employee_id}/remove",
        method="POST",
        operation_id="remove_member",
        summary="Remove a member: their sessions end and their personal token stops working.",
        answers=Members,
        changes=True,
    ),
    Declaration(
        path="/members/{employee_id}/change",
        method="POST",
        operation_id="change_member",
        summary="Correct a member's name or the GitHub account they sign in with.",
        answers=Members,
        changes=True,
        accepts=ChangedMember,
    ),
    Declaration(
        path="/members/{employee_id}/admin",
        method="POST",
        operation_id="set_admin",
        summary="Grant admin to a member, or take it away.",
        answers=Members,
        changes=True,
        accepts=AdminChange,
    ),
    Declaration(
        path="/members/{employee_id}/ownership",
        method="POST",
        operation_id="hand_over_ownership",
        summary="Make another member the team's owner.",
        answers=Members,
        changes=True,
    ),
    Declaration(
        path="/my-token",
        method="POST",
        operation_id="reissue_my_token",
        summary="Issue a new personal token for the signed-in member, revoking the one they had.",
        answers=IssuedToken,
        changes=True,
    ),
    Declaration(
        path="/members/{employee_id}/token",
        method="POST",
        operation_id="reissue_token",
        summary="Issue a new personal token for a member of the team, revoking the one they had.",
        answers=IssuedToken,
        changes=True,
    ),
    Declaration(
        path="/sign-out",
        method="POST",
        operation_id="sign_out",
        summary="End this console session.",
        answers=Status,
        changes=True,
    ),
)


def description() -> dict[str, Any]:
    """The API's OpenAPI document: what the console generates its types from."""
    paths: dict[str, Any] = {}
    schemas: dict[str, Any] = {}
    for declaration in DECLARATIONS:
        responses: dict[str, Any]
        if declaration.answers is None:
            responses = {"302": {"description": declaration.summary}}
        else:
            schema = declaration.answers.model_json_schema(ref_template="#/components/schemas/{model}")
            schemas.update(schema.pop("$defs", {}))
            schemas[declaration.answers.__name__] = schema
            responses = {
                "200": {
                    "description": declaration.summary,
                    "content": {
                        "application/json": {"schema": {"$ref": f"#/components/schemas/{declaration.answers.__name__}"}}
                    },
                }
            }
        parameters = [
            {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
            for name in re.findall(r"{(\w+)}", declaration.path)
        ] + [
            {"name": name, "in": "query", "required": False, "schema": {"type": "string"}}
            for name in declaration.query
        ]
        body: dict[str, Any] = {}
        if declaration.accepts is not None:
            accepted = declaration.accepts.model_json_schema(ref_template="#/components/schemas/{model}")
            schemas.update(accepted.pop("$defs", {}))
            schemas[declaration.accepts.__name__] = accepted
            body = {
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{declaration.accepts.__name__}"}
                        }
                    },
                }
            }
        paths.setdefault(f"{PREFIX}{declaration.path}", {})[declaration.method.lower()] = {
            "operationId": declaration.operation_id,
            "summary": declaration.summary,
            **({"parameters": parameters} if parameters else {}),
            **body,
            "responses": responses,
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Shared Memory console API", "version": "1"},
        "paths": paths,
        "components": {"schemas": schemas},
    }


class ConsoleApi:
    """The API's behaviour: sessions in cookies, and the same refusals the memory tools give."""

    def __init__(
        self,
        settings: Settings,
        sessions: ConsoleSessions,
        audit: Audit,
        identity: Identity,
        service: MemoryService,
        briefing: Briefing,
        lifecycle: Lifecycle,
        challenges: Challenges,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._audit = audit
        self._identity = identity
        self._service = service
        self._briefing = briefing
        self._lifecycle = lifecycle
        self._challenging = challenges

    def routes(self) -> list[Route]:
        handlers: Mapping[str, Callable[[Request], Response]] = {
            "status": self._status,
            "sign_in": self._sign_in,
            "sign_in_callback": self._sign_in_callback,
            "audit": self._audit_log,
            "projects": self._projects,
            "create_project": self._create_project,
            "project": self._project,
            "rename_project": self._rename_project,
            "appoint_lead": self._appoint_lead,
            "remove_lead": self._remove_lead,
            "add_repository": self._add_repository,
            "remove_repository": self._remove_repository,
            "restrict_project": self._restrict_project,
            "grant_access": self._grant_access,
            "revoke_access": self._revoke_access,
            "tree": self._tree,
            "pins": self._pins,
            "pin": self._pin,
            "unpin": self._unpin,
            "files": self._files,
            "memory_at": self._memory_at,
            "history_at": self._history_at,
            "version_at": self._version_at,
            "difference_at": self._difference_at,
            "pin_at": self._pin_at,
            "unpin_at": self._unpin_at,
            "retire_at": self._retire_at,
            "search_everywhere": self._search_everywhere,
            "challenges": self._challenges,
            "decide_challenge": self._decide_challenge,
            "retire": self._retire,
            "memory": self._memory,
            "search": self._search,
            "history": self._history,
            "version": self._version,
            "difference": self._difference,
            "members": self._members,
            "add_member": self._add_member,
            "remove_member": self._remove_member,
            "change_member": self._change_member,
            "set_admin": self._set_admin,
            "hand_over_ownership": self._hand_over_ownership,
            "reissue_my_token": self._reissue_my_token,
            "reissue_token": self._reissue_token,
            "sign_out": self._sign_out,
        }
        routes = [self._route(declaration, handlers[declaration.operation_id]) for declaration in DECLARATIONS]

        async def describe(request: Request) -> Response:
            return JSONResponse(description())

        return routes + [Route(f"{PREFIX}/openapi.json", describe, methods=["GET"], name="openapi")]

    def _route(self, declaration: Declaration, handle: Callable[[Request], Response]) -> Route:
        async def endpoint(request: Request) -> Response:
            if declaration.changes and CONSOLE_HEADER not in request.headers:
                return JSONResponse({"message": "This request didn't come from the console."}, status_code=403)
            if declaration.accepts is not None:
                try:
                    request.state.asked = declaration.accepts.model_validate(await request.json())
                except (ValueError, ValidationError) as wrong:
                    return JSONResponse({"message": _plainly(wrong)}, status_code=422)
            return await anyio.to_thread.run_sync(handle, request)

        return Route(
            f"{PREFIX}{declaration.path}", endpoint, methods=[declaration.method], name=declaration.operation_id
        )

    # --- the calls ---

    def _status(self, request: Request) -> Response:
        return JSONResponse(self._describe(self._member(request)).model_dump(mode="json"))

    def _sign_in(self, request: Request) -> Response:
        try:
            return RedirectResponse(self._sessions.start(self._root(request)), status_code=302)
        except Refused as refused:
            return self._back_to_console(request, str(refused))

    def _sign_in_callback(self, request: Request) -> Response:
        code, state = request.query_params.get("code", ""), request.query_params.get("state", "")
        if not code or not state:
            return self._back_to_console(request, "That sign-in didn't finish. Try again.")
        try:
            token = self._sessions.finish(code, state, self._root(request))
        except Refused as refused:
            return self._back_to_console(request, str(refused))
        signed_in = RedirectResponse(self._console_url(request), status_code=303)
        signed_in.set_cookie(
            COOKIE,
            token,
            max_age=int(self._settings.console_session_days * 24 * 60 * 60),
            httponly=True,
            secure=self._https(request),
            samesite="lax",
            path="/",
        )
        return signed_in

    def _projects(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        answer = Projects(projects=[ProjectSummary(**one) for one in self._identity.project_summaries(member)])
        return JSONResponse(answer.model_dump(mode="json"))

    def _create_project(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked: ProjectName = request.state.asked
        try:
            project = self._identity.create_project(self._identity.caller_in(member, None), asked.name)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        self._audit.record(PROJECT_CREATED, member=member, project_id=project.project_id, detail={"name": project.name})
        return self._project_now(request, member, project.project_id)

    def _project(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        return self._project_now(request, member, request.path_params["project_id"])

    def _rename_project(self, request: Request) -> Response:
        def rename(member: Member, caller: Caller, project_id: str) -> None:
            asked: ProjectName = request.state.asked
            self._identity.rename_project(caller, project_id, asked.name)
            self._audit.record(PROJECT_RENAMED, member=member, project_id=project_id, detail={"name": asked.name})

        return self._change_project(request, rename)

    def _appoint_lead(self, request: Request) -> Response:
        def appoint(member: Member, caller: Caller, project_id: str) -> None:
            asked: Appointment = request.state.asked
            self._identity.appoint_lead(caller, project_id, asked.employee_id)
            self._audit.record(LEAD_APPOINTED, member=member, project_id=project_id, target=asked.employee_id)

        return self._change_project(request, appoint)

    def _remove_lead(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller, project_id: str) -> None:
            employee_id = request.path_params["employee_id"]
            self._identity.remove_lead(caller, project_id, employee_id)
            self._audit.record(LEAD_REMOVED, member=member, project_id=project_id, target=employee_id)

        return self._change_project(request, remove)

    def _add_repository(self, request: Request) -> Response:
        def add(member: Member, caller: Caller, project_id: str) -> None:
            asked: RepositoryName = request.state.asked
            self._identity.add_repository(caller, project_id, asked.name)
            self._audit.record(REPOSITORY_ADDED, member=member, project_id=project_id, target=asked.name)

        return self._change_project(request, add)

    def _remove_repository(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller, project_id: str) -> None:
            repository = request.path_params["repository"]
            self._identity.remove_repository(caller, project_id, repository)
            self._audit.record(REPOSITORY_REMOVED, member=member, project_id=project_id, target=repository)

        return self._change_project(request, remove)

    def _restrict_project(self, request: Request) -> Response:
        def restrict(member: Member, caller: Caller, project_id: str) -> None:
            asked: Restriction = request.state.asked
            self._identity.restrict(caller, project_id, asked.restricted)
            self._audit.record(
                PROJECT_RESTRICTED if asked.restricted else PROJECT_OPENED, member=member, project_id=project_id
            )

        return self._change_project(request, restrict)

    def _grant_access(self, request: Request) -> Response:
        def grant(member: Member, caller: Caller, project_id: str) -> None:
            asked: AccessChange = request.state.asked
            self._identity.grant_access(caller, project_id, asked.employee_id)
            self._audit.record(ACCESS_GRANTED, member=member, project_id=project_id, target=asked.employee_id)

        return self._change_project(request, grant)

    def _revoke_access(self, request: Request) -> Response:
        def revoke(member: Member, caller: Caller, project_id: str) -> None:
            employee_id = request.path_params["employee_id"]
            self._identity.revoke_access(caller, project_id, employee_id)
            self._audit.record(ACCESS_REVOKED, member=member, project_id=project_id, target=employee_id)

        return self._change_project(request, revoke)

    def _change_project(self, request: Request, change: Callable[[Member, Caller, str], None]) -> Response:
        """Everything a lead or an admin does to one project: the same guard, and the project as it now stands."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        project_id = request.path_params["project_id"]
        try:
            change(member, self._identity.caller_in(member, project_id), project_id)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return self._project_now(request, member, project_id)

    def _project_now(self, request: Request, member: Member, project_id: str) -> Response:
        try:
            found = self._identity.project_detail(member, project_id)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        server_url = str(request.base_url).rstrip("/")
        repositories = [self._repository(server_url, project_id, found["name"], name) for name in found["repositories"]]
        detail = ProjectDetail(**{**found, "repositories": repositories})
        return JSONResponse(detail.model_dump(mode="json"))

    def _repository(self, server_url: str, project_id: str, project_name: str, name: str) -> ProjectRepository:
        settings = self._service.settings_for(project_id, name)
        files = self._service.connection_files(server_url, project_id, project_name, name)
        return ProjectRepository(
            name=name, settings=json.dumps(settings, indent=2), files=[ConnectionFile(**file) for file in files]
        )

    def _tree(self, request: Request) -> Response:
        def walk(caller: Caller) -> Tree:
            walked = self._service.tree(caller, request.query_params.get("level"))
            pinned = self._briefing.pinned_paths(caller.team)
            for folder in walked["folders"]:
                folder["pinnable"] = _may_be_pinned(folder["folder"])
                folder["pinned"] = folder["folder"] in pinned
                for memory in folder["memories"]:
                    memory["pinned"] = memory["path"] in pinned
            return Tree(**walked)

        return self._browse(request, walk)

    def _memory(self, request: Request) -> Response:
        return self._browse(request, lambda caller: self._detail(caller, request.query_params.get("path", "")))

    def _detail(self, caller: Caller, path: str) -> MemoryDetail:
        """One memory in full: what it says, its file as Claude reads it, and whether it is pinned."""
        memory = self._service.read(caller, path)
        memory["pinned"] = memory["path"] in self._briefing.pinned_paths(caller.team)
        memory["source"] = self._service.source(caller, path)
        memory["author_name"] = self._names(caller.member).get(memory["author"], memory["author"])
        return MemoryDetail(**memory)

    def _names(self, member: Member) -> dict[str, str]:
        return {one["employee_id"]: one["name"] for one in self._identity.members(member)}

    # --- memory by its path, wherever it lives ---

    def _files(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            caller = self._identity.caller_in(member, None)
            found = self._service.explore(
                caller, request.query_params.get("folder", ""), deep=request.query_params.get("deep") == "1"
            )
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        pinned = self._briefing.pinned_paths(caller.team)
        for memory in [*found["memories"], *(one for section in found["inside"] for one in section["memories"])]:
            memory["pinned"] = memory["path"] in pinned
        found["pinnable"] = bool(found["folder"]) and _may_be_pinned(found["folder"])
        found["pinned"] = found["folder"] in pinned
        return JSONResponse(Folder(**found).model_dump(mode="json"))

    def _memory_at(self, request: Request) -> Response:
        return self._at(request, self._detail)

    def _history_at(self, request: Request) -> Response:
        return self._at(request, lambda caller, path: MemoryHistory(**self._service.history(caller, path)))

    def _version_at(self, request: Request) -> Response:
        def read(caller: Caller, path: str) -> MemoryAtVersion:
            return MemoryAtVersion(**self._service.version(caller, path, request.query_params.get("commit", "")))

        return self._at(request, read)

    def _difference_at(self, request: Request) -> Response:
        def read(caller: Caller, path: str) -> MemoryDifference:
            asked = request.query_params
            return MemoryDifference(
                **self._service.difference(caller, path, asked.get("before", ""), asked.get("after", ""))
            )

        return self._at(request, read)

    def _pin_at(self, request: Request) -> Response:
        def pin(caller: Caller, path: str) -> PinState:
            return PinState(path=self._briefing.pin(caller, path)["pinned"], pinned=True)

        return self._at(request, pin, request.state.asked.path)

    def _unpin_at(self, request: Request) -> Response:
        def unpin(caller: Caller, path: str) -> PinState:
            return PinState(path=self._briefing.unpin(caller, path)["unpinned"], pinned=False)

        return self._at(request, unpin, request.state.asked.path)

    def _retire_at(self, request: Request) -> Response:
        def retire(caller: Caller, path: str) -> Retired:
            done = self._lifecycle.retire(caller, path)
            return Retired(status=done["status"], path=path, challenge_id=done.get("challenge_id"))

        return self._at(request, retire, request.state.asked.path)

    def _search_everywhere(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked = request.query_params
        try:
            found = self._service.search_everywhere(
                self._identity.caller_in(member, None),
                asked.get("query", ""),
                level=asked.get("level") or None,
                type=asked.get("type") or None,
                limit=int(asked.get("limit", 20)),
            )
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        except ValueError:
            return JSONResponse({"message": "That search wasn't understood."}, status_code=422)
        results = [SearchHit(**{**hit, "project_id": _project_in(hit["path"])}) for hit in found["results"]]
        return JSONResponse(SearchResults(results=results).model_dump(mode="json"))

    def _at(
        self, request: Request, look: Callable[[Caller, str], BaseModel], path: str | None = None
    ) -> Response:
        """Anything done to one memory by its path, placed in the project it lives in (or any, for team memory)."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        where = request.query_params.get("path", "") if path is None else path
        try:
            return JSONResponse(look(self._working_in(member, _project_in(where)), where).model_dump(mode="json"))
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        except ValueError:
            return JSONResponse({"message": "That request wasn't understood."}, status_code=422)

    def _pins(self, request: Request) -> Response:
        return self._browse(request, self._pinned)

    def _pin(self, request: Request) -> Response:
        def pin(caller: Caller) -> Pins:
            asked: MemoryPath = request.state.asked
            self._briefing.pin(caller, asked.path)
            return self._pinned(caller)

        return self._browse(request, pin)

    def _unpin(self, request: Request) -> Response:
        def unpin(caller: Caller) -> Pins:
            asked: MemoryPath = request.state.asked
            self._briefing.unpin(caller, asked.path)
            return self._pinned(caller)

        return self._browse(request, unpin)

    def _pinned(self, caller: Caller) -> Pins:
        pins = [Pin(**one) for one in self._briefing.listed(caller)]
        return Pins(
            pins=pins, tokens=sum(pin.tokens for pin in pins), cap=self._settings.briefing_cap_tokens
        )

    def _search(self, request: Request) -> Response:
        def search(caller: Caller) -> SearchResults:
            asked = request.query_params
            found = self._service.search(
                caller,
                asked.get("query", ""),
                level=asked.get("level") or None,
                type=asked.get("type") or None,
                limit=int(asked.get("limit", 10)),
            )
            return SearchResults(
                results=[SearchHit(**{**hit, "project_id": _project_in(hit["path"])}) for hit in found["results"]]
            )

        return self._browse(request, search)

    def _history(self, request: Request) -> Response:
        def read(caller: Caller) -> MemoryHistory:
            return MemoryHistory(**self._service.history(caller, request.query_params.get("path", "")))

        return self._browse(request, read)

    def _version(self, request: Request) -> Response:
        def read(caller: Caller) -> MemoryAtVersion:
            asked = request.query_params
            return MemoryAtVersion(
                **self._service.version(caller, asked.get("path", ""), asked.get("commit", ""))
            )

        return self._browse(request, read)

    def _difference(self, request: Request) -> Response:
        def read(caller: Caller) -> MemoryDifference:
            asked = request.query_params
            return MemoryDifference(
                **self._service.difference(
                    caller, asked.get("path", ""), asked.get("before", ""), asked.get("after", "")
                )
            )

        return self._browse(request, read)

    def _challenges(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        return self._disputes(self._identity.caller_in(member, None))

    def _decide_challenge(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked: Decision = request.state.asked
        try:
            challenge_id = int(request.path_params["challenge_id"])
        except ValueError:
            return JSONResponse({"message": "That isn't a challenge."}, status_code=422)
        challenge = self._challenging.open_challenge(member.team_code, challenge_id)
        if challenge is None:
            return JSONResponse(
                {"message": f"There is no open challenge {challenge_id} in your team."}, status_code=403
            )
        try:
            self._lifecycle.decide_challenge(self._working_in(member, project_of(challenge)), challenge_id, asked.decision)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return self._disputes(self._identity.caller_in(member, None))

    def _retire(self, request: Request) -> Response:
        def retire(caller: Caller) -> Retired:
            asked: MemoryPath = request.state.asked
            done = self._lifecycle.retire(caller, asked.path)
            return Retired(
                status=done["status"],
                path=asked.path,
                challenge_id=done.get("challenge_id"),
            )

        return self._browse(request, retire)

    def _disputes(self, caller: Caller) -> Response:
        waiting = [self._dispute(caller, challenge) for challenge in self._challenging.waiting_for(caller)]
        raised = [
            RaisedChallenge(**one, target_title=self._side(caller, one["target_path"]).title)
            for one in self._challenging.raised_by(caller)
        ]
        return JSONResponse(ChallengeList(waiting=waiting, raised=raised).model_dump(mode="json"))

    def _dispute(self, caller: Caller, challenge: Challenge) -> ChallengeDetail:
        return ChallengeDetail(
            challenge_id=challenge.id,
            kind=challenge.kind,
            project_id=project_of(challenge),
            raised_by=challenge.raised_by,
            raised_at=challenge.raised_at,
            yours=challenge.target_author == caller.member_id,
            target=self._side(caller, challenge.target_path),
            challenger=None if challenge.challenger_path is None else self._side(caller, challenge.challenger_path),
        )

    def _side(self, caller: Caller, path: str) -> ChallengedMemory:
        """One memory of a challenge, or a stand-in when it is no longer where it was."""
        try:
            memory = self._service.read(self._working_in(caller.member, _project_in(path)), path)
        except Refused:
            return ChallengedMemory(
                path=path, title=path, summary="", body="", level="", type="", author="", status="gone"
            )
        return ChallengedMemory(**{name: memory[name] for name in ChallengedMemory.model_fields})

    def _working_in(self, member: Member, project_id: str | None) -> Caller:
        """A caller placed in a project, as a session would be: the one asked for, or any the member can reach.

        The console isn't in a project the way a session is, and team memory belongs to none, so anything about
        team memory is done from a project its member can reach.
        """
        if project_id is None:
            reachable = self._identity.projects(member)
            project_id = reachable[0].project_id if reachable else None
        return self._identity.caller_in(member, project_id)

    def _browse(self, request: Request, look: Callable[[Caller], BaseModel]) -> Response:
        """Everything a member reads about one project's memory, through the same services their Claude uses."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            caller = self._identity.caller_in(member, request.path_params["project_id"])
            return JSONResponse(look(caller).model_dump(mode="json"))
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        except ValueError:
            return JSONResponse({"message": "That request wasn't understood."}, status_code=422)

    def _members(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        return self._team(member)

    def _add_member(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked: NewMember = request.state.asked
        try:
            caller = self._identity.caller_in(member, None)
            token = self._identity.add_member(caller, asked.employee_id, asked.name, github=asked.github)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        self._audit.record(
            MEMBER_ADDED, member=member, target=asked.employee_id, detail={"name": asked.name, "github": asked.github}
        )
        self._audit.record(TOKEN_ISSUED, member=member, target=asked.employee_id, detail={"for": asked.employee_id})
        return self._issued(request, asked.employee_id, token)

    def _remove_member(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller, employee_id: str) -> None:
            self._identity.remove_member(caller, employee_id)
            self._sessions.end_all_for(employee_id, member.team_pk)
            self._audit.record(MEMBER_REMOVED, member=member, target=employee_id)

        return self._run_on_member(request, remove)

    def _change_member(self, request: Request) -> Response:
        def change(member: Member, caller: Caller, employee_id: str) -> None:
            asked: ChangedMember = request.state.asked
            self._identity.change_member(caller, employee_id, asked.name, asked.github)
            self._audit.record(
                MEMBER_CHANGED, member=member, target=employee_id, detail={"name": asked.name, "github": asked.github}
            )

        return self._run_on_member(request, change)

    def _set_admin(self, request: Request) -> Response:
        def change(member: Member, caller: Caller, employee_id: str) -> None:
            asked: AdminChange = request.state.asked
            self._identity.set_admin(caller, employee_id, asked.admin)
            self._audit.record(ADMIN_GRANTED if asked.admin else ADMIN_REVOKED, member=member, target=employee_id)

        return self._run_on_member(request, change)

    def _hand_over_ownership(self, request: Request) -> Response:
        def hand_over(member: Member, caller: Caller, employee_id: str) -> None:
            self._identity.hand_over_ownership(caller, employee_id)
            self._audit.record(OWNERSHIP_HANDED_OVER, member=member, target=employee_id)

        return self._run_on_member(request, hand_over)

    def _run_on_member(self, request: Request, change: Callable[[Member, Caller, str], None]) -> Response:
        """Everything an admin does to one member: the same guard, the same answer, the team as it now stands."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            change(member, self._identity.caller_in(member, None), request.path_params["employee_id"])
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return self._team(member)

    def _team(self, member: Member) -> Response:
        everyone = Members(members=[MemberSummary(**one) for one in self._identity.members(member)])
        return JSONResponse(everyone.model_dump(mode="json"))

    def _reissue_my_token(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        token = self._identity.reissue_own_token(member)
        self._audit.record(TOKEN_ISSUED, member=member, target=member.member_id, detail={"for": "themselves"})
        return self._issued(request, member.member_id, token)

    def _reissue_token(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        employee_id = request.path_params["employee_id"]
        try:
            token = self._identity.reissue_token(self._identity.caller_in(member, None), employee_id)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        self._audit.record(TOKEN_ISSUED, member=member, target=employee_id, detail={"for": employee_id})
        return self._issued(request, employee_id, token)

    def _issued(self, request: Request, employee_id: str, token: str) -> Response:
        issued = IssuedToken(employee_id=employee_id, personal_token=token, server_url=self._server_url(request))
        return JSONResponse(issued.model_dump(mode="json"))

    def _server_url(self, request: Request) -> str:
        """What a member puts into the plugin: the address their Claude reaches this server at."""
        return (self._settings.console_url or self._root(request)).rstrip("/")

    def _audit_log(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked = request.query_params
        try:
            page = self._audit.read(
                member,
                limit=int(asked.get("limit", 50)),
                before=int(asked["before"]) if asked.get("before") else None,
                member_id=asked.get("member") or None,
                kind=asked.get("kind") or None,
                project_id=asked.get("project") or None,
                since=_moment(asked.get("since"), time.min),
                until=_moment(asked.get("until"), time.max),
            )
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        except ValueError:
            return JSONResponse({"message": "That filter wasn't understood."}, status_code=422)
        answer = AuditPage(
            events=[AuditEvent(**vars(event)) for event in page.events],
            next=page.next,
        )
        return JSONResponse(answer.model_dump(mode="json"))

    def _sign_out(self, request: Request) -> Response:
        self._sessions.end(request.cookies.get(COOKIE))
        signed_out = JSONResponse(self._describe(None).model_dump(mode="json"))
        signed_out.delete_cookie(COOKIE, path="/", httponly=True, secure=self._https(request), samesite="lax")
        return signed_out

    # --- shared bits ---

    def _member(self, request: Request) -> Member | None:
        return self._sessions.member_for(request.cookies.get(COOKIE))

    def _describe(self, member: Member | None) -> Status:
        return Status(
            signed_in=member is not None,
            github_sign_in=self._sessions.configured,
            member=None
            if member is None
            else SignedInMember(
                employee_id=member.member_id,
                name=member.name,
                team=member.team_code,
                role=member.role,  # type: ignore[arg-type]
                leads_a_project=bool(self._identity.leads_of(member)),
            ),
        )

    def _root(self, request: Request) -> str:
        return str(request.base_url).rstrip("/")

    def _console_url(self, request: Request) -> str:
        return (self._settings.console_url or self._root(request)).rstrip("/") + "/"

    def _https(self, request: Request) -> bool:
        return (self._settings.console_url or self._root(request)).startswith("https://")

    def _back_to_console(self, request: Request, message: str) -> Response:
        return RedirectResponse(f"{self._console_url(request)}?sign-in-error={quote(message)}", status_code=303)
