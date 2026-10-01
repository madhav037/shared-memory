"""The console's JSON API: what serving each declared call actually does.

It is another transport onto the same services the memory tools use, like the hook endpoints. Every call is declared
once in `console_contract.py`, with the shape it answers with, so the console's types can be generated from that
description and can't drift away from it. This module turns each declaration into a route.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time
from typing import Any
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
from shared_memory.board import COLUMNS, Board
from shared_memory.briefing import Briefing, pin_target
from shared_memory.challenges import Challenge, Challenges, project_of
from shared_memory.config import Settings
from shared_memory.console_memory import ConsoleMemory
from shared_memory.console_sessions import COOKIE, ConsoleSessions
from shared_memory.console_contract import (
    AccessChange, AdminChange, Appointment, AuditEvent, AuditPage, BoardArchive, BoardColumn, Card, CardCommentText,
    CardDetail, CardFields, CardMove, ChallengeDetail, DeletedCard, NewCard, ChallengeList, ChallengedMemory,
    ChangedMember, ConnectionFile, DECLARATIONS, Decision, Declaration, Folder, IssuedToken, MemberSummary, Members,
    MemoryAtVersion, MemoryDetail, MemoryHistory, MemoryPath, MovedCard, NewMember, PREFIX, Pin, PinState,
    Pins, ProjectBoard, ProjectDetail, ProjectName, ProjectRepository, ProjectSummary, Projects, RaisedChallenge,
    RepositoryName,
    Restriction, Retired, SearchHit, SearchResults, SignedInMember, Status, description,
)
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Member
from shared_memory.lifecycle import Lifecycle
from shared_memory.memory import locate
from shared_memory.saves import Saves
from shared_memory.service import MemoryService

CONSOLE_HEADER = "x-shared-memory-console"

# The calls that save memory (retiring, deciding a challenge, and moving a card, which retires the known issues it
# fixes when it lands in Done). They wait for their turn with every other save, without holding a worker thread (see
# `saves.py`).
SAVING = frozenset({"retire_at", "decide_challenge", "move_card"})


# The board's refusals are written for a coding agent and name its tools and their fields. In the console the same
# refusal names what a member has in front of them instead.
_BOARD_WORDS = (
    (" with claim_card", ""),
    ("with comment_card", "in a comment"),
    ("A blocked_reason", "The reason"),
    ("a blocked_reason", "a reason"),
)


def _on_the_board(refusal: str) -> str:
    """One of the board's refusals, as the console says it."""
    for tool_word, console_word in _BOARD_WORDS:
        refusal = refusal.replace(tool_word, console_word)
    return refusal


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


class ConsoleApi:
    """The API's behaviour: sessions in cookies, and the same refusals the memory tools give."""

    def __init__(
        self,
        settings: Settings,
        sessions: ConsoleSessions,
        audit: Audit,
        identity: Identity,
        service: MemoryService,
        explorer: ConsoleMemory,
        briefing: Briefing,
        lifecycle: Lifecycle,
        challenges: Challenges,
        saves: Saves,
        board: Board,
    ) -> None:
        self._settings = settings
        self._board = board
        self._saves = saves
        self._sessions = sessions
        self._audit = audit
        self._identity = identity
        self._service = service
        self._explorer = explorer
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
            "board": self._board_of,
            "board_archive": self._board_archive,
            "card": self._card,
            "add_card": self._add_card,
            "edit_card": self._edit_card,
            "move_card": self._move_card,
            "claim_card": self._claim_card,
            "comment_card": self._comment_card,
            "delete_card": self._delete_card,
            "restrict_project": self._restrict_project,
            "grant_access": self._grant_access,
            "revoke_access": self._revoke_access,
            "pins": self._pins,
            "files": self._files,
            "memory_at": self._memory_at,
            "history_at": self._history_at,
            "version_at": self._version_at,
            "pin_at": self._pin_at,
            "unpin_at": self._unpin_at,
            "retire_at": self._retire_at,
            "search_everywhere": self._search_everywhere,
            "challenges": self._challenges,
            "decide_challenge": self._decide_challenge,
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
        assert SAVING <= handlers.keys()
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
            if declaration.operation_id in SAVING:
                return await self._saves.run(handle, request)
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
            self._identity.appoint_lead(caller, project_id, asked.member_id)
            self._audit.record(LEAD_APPOINTED, member=member, project_id=project_id, target=asked.member_id)

        return self._change_project(request, appoint)

    def _remove_lead(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller, project_id: str) -> None:
            member_id = request.path_params["member_id"]
            self._identity.remove_lead(caller, project_id, member_id)
            self._audit.record(LEAD_REMOVED, member=member, project_id=project_id, target=member_id)

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
            self._identity.grant_access(caller, project_id, asked.member_id)
            self._audit.record(ACCESS_GRANTED, member=member, project_id=project_id, target=asked.member_id)

        return self._change_project(request, grant)

    def _revoke_access(self, request: Request) -> Response:
        def revoke(member: Member, caller: Caller, project_id: str) -> None:
            member_id = request.path_params["member_id"]
            self._identity.revoke_access(caller, project_id, member_id)
            self._audit.record(ACCESS_REVOKED, member=member, project_id=project_id, target=member_id)

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
        files = self._service.connection_files(server_url, project_id, project_name, name)
        return ProjectRepository(name=name, files=[ConnectionFile(**file) for file in files])

    def _detail(self, caller: Caller, path: str) -> MemoryDetail:
        """One memory in full: what it says, its file as Claude reads it, and whether it is pinned."""
        memory = self._service.read(caller, path)
        memory["pinned"] = memory["path"] in self._briefing.pinned_paths(caller.team)
        memory["source"] = self._service.source(caller, path)
        memory["author_name"] = self._names(caller.member).get(memory["author"], memory["author"])
        return MemoryDetail(**memory)

    def _names(self, member: Member) -> dict[str, str]:
        return {one["member_id"]: one["name"] for one in self._identity.members(member)}

    # --- a project's board, read ---

    def _board_of(self, request: Request) -> Response:
        def read(caller: Caller) -> ProjectBoard:
            found = self._board.read(caller, *self._card_filters(request))
            names = self._names(caller.member)
            columns = [
                BoardColumn.model_validate(
                    {"column": column, "name": name, "cards": [self._card_of(one, names) for one in cards]}
                )
                for column, name in COLUMNS.items()
                for cards in [found["columns"][column]]
            ]
            return ProjectBoard(
                project_id=found["project_id"],
                project_name=caller.require_project().name,
                columns=columns,
                labels=found["labels"],
            )

        return self._browse(request, read)

    def _board_archive(self, request: Request) -> Response:
        def read(caller: Caller) -> BoardArchive:
            found = self._board.read(caller, *self._card_filters(request), archive=True)
            names = self._names(caller.member)
            return BoardArchive(
                project_id=found["project_id"],
                project_name=caller.require_project().name,
                cards=[self._card_of(one, names) for one in found["archive"]],
            )

        return self._browse(request, read)

    def _card(self, request: Request) -> Response:
        def read(caller: Caller) -> CardDetail:
            return self._card_detail(caller, self._board.card(caller, self._card_number(request)))

        return self._browse(request, read)

    def _card_detail(self, caller: Caller, found: dict[str, Any]) -> CardDetail:
        """A card as the board module gives it, whole: with its members named and its links' titles."""
        titles: dict[str, str] = {}
        for path in [*found["memories"], *found["known_issues"]]:
            try:
                titles[path] = self._service.read(caller, path)["title"]
            except Refused:
                continue  # gone, or out of this member's reach: the console shows its path instead
        card = self._card_of(found, self._names(caller.member))
        return CardDetail(**card.model_dump(), titles=titles)

    @staticmethod
    def _card_number(request: Request) -> int:
        try:
            return int(request.path_params["number"])
        except ValueError:
            raise Refused(f"{request.path_params['number']!r} isn't a card number.") from None

    # --- a project's board, changed: through the board module, so the tools' rules and refusals hold (ADR-0014) ---

    def _add_card(self, request: Request) -> Response:
        def add(caller: Caller) -> CardDetail:
            asked: NewCard = request.state.asked
            found = self._board.add(
                caller, asked.title, asked.description, asked.priority, asked.labels, asked.due_date
            )
            return self._card_detail(caller, found)

        return self._browse(request, add, _on_the_board)

    def _edit_card(self, request: Request) -> Response:
        def edit(caller: Caller) -> CardDetail:
            asked: CardFields = request.state.asked
            found = self._board.update(caller, self._card_number(request), **asked.model_dump(exclude_none=True))
            return self._card_detail(caller, found)

        return self._browse(request, edit, _on_the_board)

    def _move_card(self, request: Request) -> Response:
        def move(caller: Caller) -> MovedCard:
            asked: CardMove = request.state.asked
            found = self._board.update(caller, self._card_number(request), **asked.model_dump(exclude_none=True))
            # The board retires what the card fixed as the tools do (ADR-0014); each outcome is retire's own.
            fixed = [
                Retired(
                    status=one["status"], path=one.get("path") or one["challenges"], challenge_id=one.get("challenge_id")
                )
                for one in found.get("known_issues_fixed", [])
            ]
            return MovedCard(**self._card_detail(caller, found).model_dump(), known_issues_fixed=fixed)

        return self._browse(request, move, _on_the_board)

    def _claim_card(self, request: Request) -> Response:
        def claim(caller: Caller) -> CardDetail:
            return self._card_detail(caller, self._board.claim(caller, self._card_number(request)))

        return self._browse(request, claim, _on_the_board)

    def _comment_card(self, request: Request) -> Response:
        def comment(caller: Caller) -> CardDetail:
            asked: CardCommentText = request.state.asked
            return self._card_detail(caller, self._board.comment(caller, self._card_number(request), asked.text))

        return self._browse(request, comment, _on_the_board)

    def _delete_card(self, request: Request) -> Response:
        def delete(caller: Caller) -> DeletedCard:
            return DeletedCard(number=self._board.delete(caller, self._card_number(request))["deleted"])

        return self._browse(request, delete, _on_the_board)

    @staticmethod
    def _card_filters(request: Request) -> tuple[None, str | None, str | None, str | None]:
        """The board's filters as the console asks for them: no column (the board shows all four), then assignee,
        label and priority."""
        asked = request.query_params
        return None, asked.get("assignee") or None, asked.get("label") or None, asked.get("priority") or None

    @staticmethod
    def _card_of(card: dict[str, Any], names: dict[str, str]) -> Card:
        """A card as the board module gives it, with every member it names also named in words."""
        assignee = card["assignee"]
        comments = [{**one, "author_name": names.get(one["author"], one["author"])} for one in card["comments"]]
        return Card(
            **{
                **card,
                "creator_name": names.get(card["creator"], card["creator"]),
                "assignee_name": None if assignee is None else names.get(assignee, assignee),
                "comments": comments,
            }
        )

    # --- memory by its path, wherever it lives ---

    def _files(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            caller = self._identity.caller_in(member, None)
            found = self._explorer.explore(
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

    def _pin_at(self, request: Request) -> Response:
        def pin(caller: Caller, path: str) -> PinState:
            # Briefing answers in the memory tool's shape, so the path it pinned comes back under "pinned".
            return PinState(path=self._briefing.pin(caller, path)["pinned"], pinned=True)

        return self._at(request, pin, request.state.asked.path)

    def _unpin_at(self, request: Request) -> Response:
        def unpin(caller: Caller, path: str) -> PinState:
            # As above: "unpinned" is the key, the value is the path.
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

    def _pinned(self, caller: Caller) -> Pins:
        pins = [Pin(**one) for one in self._briefing.listed(caller)]
        return Pins(
            pins=pins, tokens=sum(pin.tokens for pin in pins), cap=self._settings.briefing_cap_tokens
        )

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
            reasoning=challenge.reasoning,
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

    def _browse(
        self, request: Request, look: Callable[[Caller], BaseModel], said: Callable[[str], str] = str
    ) -> Response:
        """Everything a member reads about one project, or does to its board, through the services their Claude uses.
        `said` puts a refusal into the console's words where the service's own are an agent's."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            caller = self._identity.caller_in(member, request.path_params["project_id"])
            return JSONResponse(look(caller).model_dump(mode="json"))
        except Refused as refused:
            return JSONResponse({"message": said(str(refused))}, status_code=403)
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
            token = self._identity.add_member(caller, asked.member_id, asked.name, github=asked.github)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        self._audit.record(
            MEMBER_ADDED, member=member, target=asked.member_id, detail={"name": asked.name, "github": asked.github}
        )
        self._audit.record(TOKEN_ISSUED, member=member, target=asked.member_id, detail={"for": asked.member_id})
        return self._issued(request, asked.member_id, token)

    def _remove_member(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller, member_id: str) -> None:
            self._identity.remove_member(caller, member_id)
            self._sessions.end_all_for(member_id, member.team_pk)
            self._audit.record(MEMBER_REMOVED, member=member, target=member_id)

        return self._run_on_member(request, remove)

    def _change_member(self, request: Request) -> Response:
        def change(member: Member, caller: Caller, member_id: str) -> None:
            asked: ChangedMember = request.state.asked
            self._identity.change_member(caller, member_id, asked.name, asked.github)
            self._audit.record(
                MEMBER_CHANGED, member=member, target=member_id, detail={"name": asked.name, "github": asked.github}
            )

        return self._run_on_member(request, change)

    def _set_admin(self, request: Request) -> Response:
        def change(member: Member, caller: Caller, member_id: str) -> None:
            asked: AdminChange = request.state.asked
            self._identity.set_admin(caller, member_id, asked.admin)
            self._audit.record(ADMIN_GRANTED if asked.admin else ADMIN_REVOKED, member=member, target=member_id)

        return self._run_on_member(request, change)

    def _hand_over_ownership(self, request: Request) -> Response:
        def hand_over(member: Member, caller: Caller, member_id: str) -> None:
            self._identity.hand_over_ownership(caller, member_id)
            self._audit.record(OWNERSHIP_HANDED_OVER, member=member, target=member_id)

        return self._run_on_member(request, hand_over)

    def _run_on_member(self, request: Request, change: Callable[[Member, Caller, str], None]) -> Response:
        """Everything an admin does to one member: the same guard, the same answer, the team as it now stands."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            change(member, self._identity.caller_in(member, None), request.path_params["member_id"])
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
        member_id = request.path_params["member_id"]
        try:
            token = self._identity.reissue_token(self._identity.caller_in(member, None), member_id)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        self._audit.record(TOKEN_ISSUED, member=member, target=member_id, detail={"for": member_id})
        return self._issued(request, member_id, token)

    def _issued(self, request: Request, member_id: str, token: str) -> Response:
        issued = IssuedToken(member_id=member_id, personal_token=token, server_url=self._server_url(request))
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
                member_id=member.member_id,
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
