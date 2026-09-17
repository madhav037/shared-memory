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
from shared_memory.config import Settings
from shared_memory.console_sessions import COOKIE, ConsoleSessions
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Member
from shared_memory.service import MemoryService

PREFIX = "/api"
CONSOLE_HEADER = "x-shared-memory-console"


def _plainly(wrong: Exception) -> str:
    """A refusal a member can act on, rather than a validation dump."""
    if isinstance(wrong, ValidationError):
        missing = ", ".join(str(problem["loc"][-1]) for problem in wrong.errors())
        return f"That request was missing something: {missing}."
    return "That request wasn't understood."


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
    leads: list[ProjectMember]
    you_lead: bool


class Projects(BaseModel):
    projects: list[ProjectSummary]


class ProjectRepository(BaseModel):
    """A repository of a project, with what it commits to connect its sessions to the project."""

    name: str
    settings: str


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
    pending: list[PendingChallenge]


class TreeFolder(BaseModel):
    folder: str
    memories: list[TreeMemory]


class Tree(BaseModel):
    """A project's memory, folder by folder."""

    folders: list[TreeFolder]


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
    pending: list[PendingChallenge]
    open_challenges: list[OpenChallenge]


class SearchHit(BaseModel):
    path: str
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
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._audit = audit
        self._identity = identity
        self._service = service

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
        return self._project_now(member, project.project_id)

    def _project(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        return self._project_now(member, request.path_params["project_id"])

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
        return self._project_now(member, project_id)

    def _project_now(self, member: Member, project_id: str) -> Response:
        try:
            found = self._identity.project_detail(member, project_id)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        detail = ProjectDetail(
            **{**found, "repositories": [self._repository(project_id, name) for name in found["repositories"]]}
        )
        return JSONResponse(detail.model_dump(mode="json"))

    def _repository(self, project_id: str, name: str) -> ProjectRepository:
        settings = self._service.settings_for(project_id, name)
        return ProjectRepository(name=name, settings=json.dumps(settings, indent=2))

    def _tree(self, request: Request) -> Response:
        return self._browse(request, lambda caller: Tree(**self._service.tree(caller, request.query_params.get("level"))))

    def _memory(self, request: Request) -> Response:
        def read(caller: Caller) -> MemoryDetail:
            return MemoryDetail(**self._service.read(caller, request.query_params.get("path", "")))

        return self._browse(request, read)

    def _search(self, request: Request) -> Response:
        def search(caller: Caller) -> SearchResults:
            asked = request.query_params
            return SearchResults(
                **self._service.search(
                    caller,
                    asked.get("query", ""),
                    level=asked.get("level") or None,
                    type=asked.get("type") or None,
                    limit=int(asked.get("limit", 10)),
                )
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
