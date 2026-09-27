"""What the console's JSON API answers with, declared once.

Every call the console can make is declared here with the shape it answers with, and `description()` turns those
declarations into the OpenAPI document the console generates its types from. Keeping the models beside the description
is what stops the console's types drifting away from what the server sends. `console_api.py` holds the behaviour that
serves them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from shared_memory.audit import Kind

PREFIX = "/api"


class SignedInMember(BaseModel):
    """Who the console is signed in as."""

    member_id: str
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
    kind: Kind
    project_id: str | None
    target: str | None
    detail: dict[str, Any]


class AuditPage(BaseModel):
    """A page of the audit log, newest first, with where the next page starts."""

    events: list[AuditEvent]
    next: int | None


class ProjectMember(BaseModel):
    """A member named on a project."""

    member_id: str
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
    action: Literal["create", "merge"]
    how: str
    contents: str
    kept_in: Literal["repository", "machine"]


class ProjectRepository(BaseModel):
    """A repository of a project, with the files each coding agent commits to connect it to the project."""

    name: str
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

    member_id: str


class RepositoryName(BaseModel):
    """A repository's short name, unique within its project."""

    name: str


class Restriction(BaseModel):
    """Whether this project is closed to its access list, or open to the whole team."""

    restricted: bool


class AccessChange(BaseModel):
    """The member being let into this project."""

    member_id: str


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
    # Whether the member reading this is the one who may decide it: its author, or anyone once the fallback passed.
    may_decide: bool


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
    # Why the member who raised it believes the memory should go, when they said. The console shows it, never edits it.
    reasoning: str | None


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
    # Why the challenge ended as it did; why it was raised is its reasoning.
    explanation: str | None
    reasoning: str | None


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

    member_id: str
    name: str
    role: Literal["owner", "admin", "member"]
    github_login: str | None
    removed: bool


class Members(BaseModel):
    members: list[MemberSummary]


class NewMember(BaseModel):
    """A member being added to the team."""

    member_id: str
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


class IssuedToken(BaseModel):
    """A personal token, shown the once. The console never shows it again."""

    member_id: str
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
        path="/projects/{project_id}/leads/{member_id}/remove",
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
        path="/projects/{project_id}/access/{member_id}/remove",
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
        path="/members/{member_id}/remove",
        method="POST",
        operation_id="remove_member",
        summary="Remove a member: their sessions end and their personal token stops working.",
        answers=Members,
        changes=True,
    ),
    Declaration(
        path="/members/{member_id}/change",
        method="POST",
        operation_id="change_member",
        summary="Correct a member's name or the GitHub account they sign in with.",
        answers=Members,
        changes=True,
        accepts=ChangedMember,
    ),
    Declaration(
        path="/members/{member_id}/admin",
        method="POST",
        operation_id="set_admin",
        summary="Grant admin to a member, or take it away.",
        answers=Members,
        changes=True,
        accepts=AdminChange,
    ),
    Declaration(
        path="/members/{member_id}/ownership",
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
        path="/members/{member_id}/token",
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
