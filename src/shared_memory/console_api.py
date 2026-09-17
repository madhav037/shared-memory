"""The console's JSON API.

It is another transport onto the same services the memory tools use, like the hook endpoints. Every call is declared
once, with the shape it answers with: the declarations serve the requests and describe the API, so the console's types
can be generated from that description and can't drift away from it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Literal
from urllib.parse import quote

import anyio.to_thread
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from shared_memory.audit import Audit
from shared_memory.config import Settings
from shared_memory.console_sessions import COOKIE, ConsoleSessions
from shared_memory.errors import Refused
from shared_memory.identity import Member

PREFIX = "/api"
CONSOLE_HEADER = "x-shared-memory-console"


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
    role: Literal["owner", "member"]


class Status(BaseModel):
    """Whether the console has reached the server, and who it is signed in as."""

    signed_in: bool
    github_sign_in: bool
    member: SignedInMember | None = None


class AuditEvent(BaseModel):
    """One thing that happened, and who did it."""

    id: int
    at: datetime
    actor: str
    kind: str
    project_id: str | None = None
    target: str | None = None
    detail: dict[str, Any]


class AuditPage(BaseModel):
    """A page of the audit log, newest first, with where the next page starts."""

    events: list[AuditEvent]
    next: int | None = None


@dataclass(frozen=True)
class Declaration:
    """One call the console can make, and what it answers with. A call that answers `None` redirects instead."""

    path: str
    method: str
    operation_id: str
    summary: str
    answers: type[BaseModel] | None
    changes: bool = False


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
        path="/audit",
        method="GET",
        operation_id="audit",
        summary="The team's audit log, newest first.",
        answers=AuditPage,
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
        paths.setdefault(f"{PREFIX}{declaration.path}", {})[declaration.method.lower()] = {
            "operationId": declaration.operation_id,
            "summary": declaration.summary,
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

    def __init__(self, settings: Settings, sessions: ConsoleSessions, audit: Audit) -> None:
        self._settings = settings
        self._sessions = sessions
        self._audit = audit

    def routes(self) -> list[Route]:
        handlers: Mapping[str, Callable[[Request], Response]] = {
            "status": self._status,
            "sign_in": self._sign_in,
            "sign_in_callback": self._sign_in_callback,
            "audit": self._audit_log,
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

    def _audit_log(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return JSONResponse({"message": "Sign in to the console first."}, status_code=401)
        asked = request.query_params
        try:
            page = self._audit.read(
                member,
                limit=int(asked.get("limit", 50)),
                before=int(asked["before"]) if asked.get("before") else None,
                member_id=asked.get("member") or None,
                kind=asked.get("kind") or None,
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
                role="owner" if member.is_owner else "member",
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
