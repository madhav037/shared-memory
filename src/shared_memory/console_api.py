"""The console's JSON API: what serving each declared call actually does.

It is another transport onto the same services the memory tools use, like the hook endpoints. Every call is declared
once in `console_contract.py`, with the shape it answers with, so the console's types can be generated from that
description and can't drift away from it. This module turns each declaration into a route.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import quote

import anyio.to_thread
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from shared_memory.activity import Activities, SessionActivity
from shared_memory.clock import Clock
from shared_memory.collisions import Collision, Collisions
from shared_memory.gates import Gate, Gates
from shared_memory import health
from shared_memory import onboarding
from shared_memory.handoff import HandoffNotes, Note
from shared_memory.messages import TEXT_LIMIT, Exchanged, Messages
from shared_memory.sessions import Session
from shared_memory.standby import Standby, Standbys
from shared_memory.talk import Talk
from shared_memory.unhooked import Unhooked
from shared_memory.audit import (
    ACCESS_GRANTED,
    ACCESS_REVOKED,
    ADMIN_GRANTED,
    ADMIN_REVOKED,
    LEAD_APPOINTED,
    FOUNDATION_REMOVED,
    KEEPER_ASSIGNED,
    KEEPER_REMOVED,
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
    COMPANY_EXPORTED,
    DEPARTMENT_CREATED,
    DEPARTMENT_LEAD_APPOINTED,
    DEPARTMENT_LEAD_REMOVED,
    DEPARTMENT_REMOVED,
    DEPARTMENT_RENAMED,
    PROJECT_MOVED,
    TOKEN_ISSUED,
    Audit,
)
from shared_memory.board import COLUMNS, Board
from shared_memory.briefing import Briefing, pin_target
from shared_memory.challenges import Challenge, Challenges, Doubt, Evidence, InDoubt, Waiting, project_of
from shared_memory.config import Settings
from shared_memory.console_memory import ConsoleMemory
from shared_memory.console_sessions import COOKIE, NONCE_COOKIE, STATE_MINUTES, ConsoleSessions
from shared_memory.console_contract import (
    AccessChange, ActiveSession, AdminChange, Appointment, AuditEvent, FoundationName, KeeperAssignment, AuditPage, BoardArchive, BoardColumn, Card,
    CardCommentText,
    CardDetail, CardFields, CardMove, ChallengeDetail, DeletedCard, NewCard, ChallengeList, ChallengedMemory,
    ChangedMember, ConnectionFile, DECLARATIONS, Decided, DecidedChallenges, Decision, Declaration, DoubtEvidence, Folder,
    DoubtedMemory, HeldLock, InDoubtMark, InDoubtReason, IssuedToken, MemberSummary,
    LicenseKeyText, LicenseState,
    Members,
    MemoryAtVersion, MemoryDetail, MemoryHistory, MovedCard, NewMember, Notice, Notices, PREFIX, Pin,
    PinState,
    Pins, PossiblyOutdatedMemory, ProjectBoard, ProjectDetail, ProjectHealth, ProjectName, ProjectRepository, ProjectSessions, ProjectSummary, Projects,
    RaisedChallenge, RateLimitChange, RateLimits,
    RepositoryName,
    Restriction, Retired, SearchHit, SearchResults, SignedInMember, Status, description,
    AwaitedMember, SessionStandby,
    GateAnswer, GateWait, MessageToSend, NamedSession, SessionCollision, SessionGate, SessionHandoffNote,
    SessionMessage, ChosenTimeZone, DetectedTimeZone, YourTimeZone, YourTimeZoneChoices,
    OnboardingEntry, OnboardingProgress,
    InterviewMemories, InterviewMemory,
    DepartmentAppointment, DepartmentName, DepartmentProject, DepartmentRef, Departments, DepartmentSummary,
    ProjectMember, ProjectMove,
)
from shared_memory.departments import Department, Departments as DepartmentStore
from shared_memory.errors import Refused
from shared_memory.export import CompanyExport
from shared_memory.identity import Caller, Identity, Member
from shared_memory.licensing import Licenses
from shared_memory.ratelimit import Limits
from shared_memory.ratelimit import RateLimits as RateLimiter
from shared_memory.lifecycle import Lifecycle
from shared_memory.locks import Locks
from shared_memory.memory import Memory, locate
from shared_memory.saves import Saves
from shared_memory.service import MemoryService
from shared_memory.suspected import reasons_in
from shared_memory import time_zone
from shared_memory.time_zone import MemberTimeZone, NotATimeZone
from shared_memory.uses import Uses

CONSOLE_HEADER = "x-shared-memory-console"

# The calls that save memory (retiring, deciding a challenge, moving a card, which retires the known issues it fixes
# when it lands in Done, and removing a department, which retires its department memory). They wait for their turn
# with every other save, without holding a worker thread (see `saves.py`).
SAVING = frozenset({"retire_at", "decide_challenge", "move_card", "remove_department"})

# The calls a read-only server refuses (a hosted server whose license key has lapsed, ADR-0022), the ones the memory
# tools refuse too: every change to memory, inviting members and creating cards. Removing members, revoking personal
# tokens, exporting and installing a renewed key keep working, as do card edits.
REFUSED_WHILE_READ_ONLY = frozenset(
    {
        "retire_at",
        "decide_challenge",
        "pin_at",
        "unpin_at",
        "create_project",
        "add_foundation",
        "add_member",
        "add_card",
        "remove_department",
    }
)


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


# How long the console keeps showing a notice the member's session has already had, and how many it shows at most.
NOTICE_DAYS = 7
NOTICE_LIMIT = 20

# A notice is only its words, so the card it is about is read back out of them: the board names a card as
# `card 4 "Its title" in project-id`, the member's own as `your card 4 "…"`, and cards returned to To do after
# `can no longer reach project-id, so`. Whatever is found is then looked up, so a notice never links to a card or a
# board that isn't there for this member.
_CARD_NAMED = re.compile(r'[Cc]ard (\d+) ".*?" in ([a-z0-9][a-z0-9-]*)')
_YOUR_CARD = re.compile(r'your card (\d+) "')
_CARDS_RETURNED = re.compile(r"can no longer reach ([a-z0-9][a-z0-9-]*), so (?:card (\d+) |cards )")


def _card_named(text: str) -> tuple[str | None, int | None]:
    """The project and the card a notice's words name, as far as they name them."""
    if named := _CARD_NAMED.search(text):
        yours = _YOUR_CARD.search(text)
        return named[2], int((yours or named)[1])
    if returned := _CARDS_RETURNED.search(text):
        return returned[1], None if returned[2] is None else int(returned[2])
    return None, None


def _plainly(wrong: Exception) -> str:
    """A refusal a member can act on, rather than a validation dump."""
    if isinstance(wrong, ValidationError):
        missing = ", ".join(str(problem["loc"][-1]) for problem in wrong.errors())
        return f"That request was missing something: {missing}."
    return "That request wasn't understood."


def _project_in(path: str) -> str | None:
    """The project a memory path belongs to, or nothing for company memory and anything unreadable."""
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


# Where the nonce cookie is sent: only to the sign-in's own addresses.
NONCE_PATH = "/api/sign-in"


def _marked(in_doubt: InDoubt | None) -> InDoubtMark | None:
    """A memory's in-doubt mark as the console is sent it, or None when nobody doubts it."""
    return None if in_doubt is None else _mark(in_doubt)


def _mark(in_doubt: InDoubt) -> InDoubtMark:
    """The in-doubt mark of a memory that is in doubt, as the console is sent it."""
    return InDoubtMark(
        count=in_doubt.count,
        reasons=[
            InDoubtReason(reason=each.reason, count=each.count, code_references=list(each.code_references))
            for each in in_doubt.reasons
        ],
        line=in_doubt.line(),
    )


def _with_evidence(challenge: dict[str, Any], doubt: Doubt | None) -> dict[str, Any]:
    """An open challenge against a memory, with a doubt's count and evidence for whoever reads the memory."""
    return {
        **challenge,
        "count": None if doubt is None else doubt.count,
        "evidence": [] if doubt is None else [_evidence(each) for each in doubt.evidence],
    }


def _evidence(each: Evidence) -> DoubtEvidence:
    reference = each.code_reference
    return DoubtEvidence(
        member_id=each.member_id,
        reasoning=each.reasoning,
        code_reference=None if reference is None else str(reference),
        quoted_line=None if reference is None else reference.quoted_line,
        raised_at=each.raised_at,
    )


def _department_ref(department: Department | None) -> DepartmentRef | None:
    return None if department is None else DepartmentRef(department_id=department.department_id, name=department.name)


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


def _named_session(session: Session, activity: str | None) -> NamedSession:
    """An active session as a collision, a gate or a message names it on the Sessions page."""
    return NamedSession(
        session_number=session.id,
        member_id=session.member_id, member_name=session.member_name, agent=session.agent, activity=activity
    )


def _named(each: SessionActivity) -> NamedSession:
    return _named_session(each.session, each.activity)


def _standby_of(standby: Standby | None, names: dict[str, str]) -> SessionStandby | None:
    """A session's standby as the Sessions page shows it, each member it awaits named; a member no longer in the company
    by their member ID."""
    if standby is None:
        return None
    return SessionStandby(
        started_at=standby.started_at,
        ends_at=standby.ends_at,
        awaits=[AwaitedMember(member_id=one, member_name=names.get(one, one)) for one in standby.awaits],
    )


@dataclass(frozen=True)
class Collided:
    """A collision between two of a project's active sessions."""

    later: SessionActivity
    earlier: SessionActivity
    collision: Collision


class SessionTalk:
    """What the Sessions page reads and does of sessions that talk (spec #507): a project's collisions, gates and
    standbys (#528), one member's sessions' messages, and that member's replies and answers. Reading marks no message
    delivered, which the
    sessions' own calls do; it keeps a gate whose wait has passed as timed out, as every read of a gate does. A reply and an answer are `Talk`'s, the same operations the session
    tools call, from one of the member's own sessions, which hears what its member did (story 38). Nothing here saves,
    edits or promotes a memory (ADR-0009, ADR-0026)."""

    def __init__(
        self,
        collisions: Collisions,
        gates: Gates,
        unhooked: Unhooked,
        messages: Messages,
        handoff_notes: HandoffNotes,
        talk: Talk,
        standbys: Standbys,
        clock: Clock,
    ) -> None:
        self._collisions = collisions
        self._gates = gates
        self._unhooked = unhooked
        self._messages = messages
        self._handoff_notes = handoff_notes
        self._talk = talk
        self._standbys = standbys
        self._clock = clock

    def now(self) -> datetime:
        return self._clock()

    def collided(self, active: Sequence[SessionActivity]) -> list[Collided]:
        """The collisions between these active sessions, the oldest first."""
        by_id = {each.session.id: each for each in active}
        found: dict[tuple[int, int], Collision] = {}
        for each in active:
            for one in self._collisions.of(each.session):
                if one.later_session_id in by_id and one.earlier_session_id in by_id:
                    found[(one.later_session_id, one.earlier_session_id)] = one
        return [
            Collided(by_id[one.later_session_id], by_id[one.earlier_session_id], one)
            for one in sorted(found.values(), key=lambda one: one.found_at)
        ]

    def gated(self, caller: Caller, project_id: str) -> list[Gate]:
        """Each session gated now, the oldest gate first, as `Gates` works it out, answers included. A wait found
        passed is kept as timed out, as any read of a gate does."""
        return self._gates.in_project(caller, project_id)

    def can_be_gated(self, active: Sequence[SessionActivity]) -> dict[int, bool]:
        """Whether each of these sessions' edits can be refused, by its id: not in a coding agent with no hooks (#518)."""
        return self._unhooked.can_be_gated([each.session for each in active])

    def standing_by(self, project_id: str) -> dict[int, Standby]:
        """The standbys held now in the project, by their session's id. Reading one leaves it held."""
        return {each.session_id: each for each in self._standbys.in_project(project_id)}

    def handoff_notes(self, project_id: str) -> list[tuple[Session, Note]]:
        """The handoff notes of the project's sessions gone lately, each with its session, the most recently seen
        first. A session gone idle without one gets one put together the first time it is asked for (#515)."""
        return self._handoff_notes.recent(project_id)

    def messages(self, project_id: str, member_id: str) -> list[Exchanged]:
        """The messages this member's sessions in the project sent or were sent, still kept, the oldest first."""
        return self._messages.exchanged(project_id, member_id)

    def send(self, caller: Caller, to: str, text: str) -> None:
        """Send a message from the caller's session in the project that `Talk.speaking` picks."""
        self._talk.send(caller, self._talk.speaking(caller), to, text, from_console=True)

    def answer(self, caller: Caller, member_id: str, answer: str, text: str | None) -> list[str]:
        """The caller agrees to or refuses the gate the member with this member ID has on the caller's sessions'
        work, or answers their urgent message, from each of the caller's sessions it concerns. The names of the members
        answered."""
        answered: list[str] = []
        for session in self._talk.answering(caller, member_id):
            for name in self._talk.answer(caller, session, member_id, answer, text, from_console=True):
                if name not in answered:
                    answered.append(name)
        return answered


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
        activities: Activities,
        locks: Locks,
        uses: Uses,
        rate_limits: RateLimiter,
        licenses: Licenses,
        export: CompanyExport,
        talk: SessionTalk,
        project_health: health.ProjectHealth,
        progress: onboarding.Progress,
        departments: DepartmentStore,
    ) -> None:
        self._departments = departments
        self._progress = progress
        self._export_of = export
        self._health = project_health
        self._talk = talk
        self._settings = settings
        self._rate_limits_of = rate_limits
        self._licenses = licenses
        self._uses = uses
        self._board = board
        self._activities = activities
        self._locks = locks
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
            "sign_in_handed_over": self._sign_in_handed_over,
            "audit": self._audit_log,
            "export": self._export,
            "projects": self._projects,
            "create_project": self._create_project,
            "project": self._project,
            "rename_project": self._rename_project,
            "appoint_lead": self._appoint_lead,
            "remove_lead": self._remove_lead,
            "add_foundation": self._add_foundation,
            "remove_foundation": self._remove_foundation,
            "assign_keeper": self._assign_keeper,
            "remove_keeper": self._remove_keeper,
            "add_repository": self._add_repository,
            "remove_repository": self._remove_repository,
            "board": self._board_of,
            "board_archive": self._board_archive,
            "project_sessions": self._project_sessions,
            "project_health": self._project_health,
            "onboarding_progress": self._onboarding_progress,
            "send_message": self._send_message,
            "answer_gate": self._answer_gate,
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
            "interviewed": self._interviewed,
            "history_at": self._history_at,
            "version_at": self._version_at,
            "pin_at": self._pin_at,
            "unpin_at": self._unpin_at,
            "retire_at": self._retire_at,
            "search_everywhere": self._search_everywhere,
            "challenges": self._challenges,
            "notices": self._notices,
            "decide_challenge": self._decide_challenge,
            "rate_limits": self._rate_limits,
            "change_rate_limits": self._change_rate_limits,
            "license_state": self._license_state,
            "install_license": self._install_license,
            "members": self._members,
            "add_member": self._add_member,
            "remove_member": self._remove_member,
            "change_member": self._change_member,
            "set_admin": self._set_admin,
            "hand_over_ownership": self._hand_over_ownership,
            "reissue_my_token": self._reissue_my_token,
            "my_time_zone": self._my_time_zone,
            "choose_my_time_zone": self._choose_my_time_zone,
            "report_my_time_zone": self._report_my_time_zone,
            "reissue_token": self._reissue_token,
            "departments": self._departments_listed,
            "create_department": self._create_department,
            "rename_department": self._rename_department,
            "remove_department": self._remove_department,
            "appoint_department_lead": self._appoint_department_lead,
            "remove_department_lead": self._remove_department_lead,
            "move_project_in": self._move_project_in,
            "move_project_out": self._move_project_out,
            "sign_out": self._sign_out,
        }
        assert SAVING <= handlers.keys()
        assert REFUSED_WHILE_READ_ONLY <= handlers.keys()
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
                if declaration.operation_id in REFUSED_WHILE_READ_ONLY:
                    # Refused before it waits for its turn with every other save.
                    refused = await anyio.to_thread.run_sync(self._read_only_refusal, request)
                    if refused is not None:
                        return refused
                return await self._saves.run(handle, request)
            if declaration.operation_id in REFUSED_WHILE_READ_ONLY:
                return await anyio.to_thread.run_sync(self._unless_read_only, handle, request)
            return await anyio.to_thread.run_sync(handle, request)

        return Route(
            f"{PREFIX}{declaration.path}", endpoint, methods=[declaration.method], name=declaration.operation_id
        )

    def _read_only_refusal(self, request: Request) -> Response | None:
        """The refusal of a change a read-only server forbids, made before it waits for a turn or does anything. Only
        a signed-in member hears it: anyone else is told to sign in first, as always."""
        if self._member(request) is None:
            return None
        try:
            self._licenses.ensure_writable()
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return None

    def _unless_read_only(self, handle: Callable[[Request], Response], request: Request) -> Response:
        return self._read_only_refusal(request) or handle(request)

    # --- the calls ---

    def _status(self, request: Request) -> Response:
        return JSONResponse(self._describe(self._member(request), request).model_dump(mode="json"))

    def _sign_in(self, request: Request) -> Response:
        try:
            started = self._sessions.start(self._root(request))
        except Refused as refused:
            return self._back_to_console(request, str(refused))
        sent = RedirectResponse(started.url, status_code=302)
        if started.nonce is not None:
            sent.set_cookie(
                NONCE_COOKIE,
                started.nonce,
                max_age=STATE_MINUTES * 60,
                httponly=True,
                secure=self._https(request),
                samesite="lax",
                path=NONCE_PATH,
            )
        return sent

    def _sign_in_callback(self, request: Request) -> Response:
        code, state = request.query_params.get("code", ""), request.query_params.get("state", "")
        if not code or not state:
            return self._back_to_console(request, "That sign-in didn't finish. Try again.")
        try:
            token = self._sessions.finish(code, state, self._root(request))
        except Refused as refused:
            return self._back_to_console(request, str(refused))
        return self._signed_in(request, token)

    def _sign_in_handed_over(self, request: Request) -> Response:
        handed_over = request.query_params.get("sign_in", "")
        if not handed_over:
            return self._back_to_console(request, "That sign-in didn't finish. Try again.")
        try:
            token = self._sessions.finish_handed_over(handed_over, request.cookies.get(NONCE_COOKIE))
        except Refused as refused:
            answer = self._back_to_console(request, str(refused))
        else:
            answer = self._signed_in(request, token)
        # The nonce serves one sign-in, however it went.
        answer.delete_cookie(NONCE_COOKIE, path=NONCE_PATH, httponly=True, secure=self._https(request), samesite="lax")
        return answer

    def _signed_in(self, request: Request, token: str) -> Response:
        """Back to the console, holding the new session in its cookie."""
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
        summaries = self._identity.project_summaries(member)
        found = self._departments.of_projects([one["project_id"] for one in summaries])
        answer = Projects(
            projects=[
                ProjectSummary(**one, department=_department_ref(found.get(one["project_id"]))) for one in summaries
            ]
        )
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

    def _add_foundation(self, request: Request) -> Response:
        def add(member: Member, caller: Caller, project_id: str) -> None:
            asked: FoundationName = request.state.asked
            self._lifecycle.add_foundation(caller, project_id, asked.name)

        return self._change_project(request, add)

    def _remove_foundation(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller, project_id: str) -> None:
            slug = request.path_params["foundation"]
            self._lifecycle.remove_foundation(caller, project_id, slug)
            self._audit.record(FOUNDATION_REMOVED, member=member, project_id=project_id, target=slug)

        return self._change_project(request, remove)

    def _assign_keeper(self, request: Request) -> Response:
        def assign(member: Member, caller: Caller, project_id: str) -> None:
            asked: KeeperAssignment = request.state.asked
            foundation = request.path_params["foundation"]
            self._identity.assign_keeper(caller, project_id, foundation, asked.member_id)
            self._audit.record(
                KEEPER_ASSIGNED,
                member=member,
                project_id=project_id,
                target=asked.member_id,
                detail={"foundation": foundation},
            )

        return self._change_project(request, assign)

    def _remove_keeper(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller, project_id: str) -> None:
            foundation = request.path_params["foundation"]
            member_id = request.path_params["member_id"]
            self._identity.remove_keeper(caller, project_id, foundation, member_id)
            self._audit.record(
                KEEPER_REMOVED, member=member, project_id=project_id, target=member_id, detail={"foundation": foundation}
            )

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
        department = _department_ref(self._departments.of_project(project_id))
        detail = ProjectDetail(**{**found, "repositories": repositories, "department": department})
        return JSONResponse(detail.model_dump(mode="json"))

    # --- departments (ADR-0032) ---

    def _departments_listed(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        return self._departments_now(member)

    def _create_department(self, request: Request) -> Response:
        def create(member: Member, caller: Caller) -> None:
            asked: DepartmentName = request.state.asked
            made = self._departments.create(caller, asked.name)
            self._audit.record(DEPARTMENT_CREATED, member=member, target=made.department_id, detail={"name": made.name})

        return self._change_departments(request, create)

    def _rename_department(self, request: Request) -> Response:
        def rename(member: Member, caller: Caller) -> None:
            asked: DepartmentName = request.state.asked
            renamed = self._departments.rename(caller, request.path_params["department_id"], asked.name)
            self._audit.record(
                DEPARTMENT_RENAMED, member=member, target=renamed.department_id, detail={"name": renamed.name}
            )

        return self._change_departments(request, rename)

    def _remove_department(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller) -> None:
            removed, left = self._departments.remove(caller, request.path_params["department_id"])
            self._audit.record(
                DEPARTMENT_REMOVED,
                member=member,
                target=removed.department_id,
                detail={"name": removed.name, "projects": left},
            )
            # Its department memory is retired, each memory audited, and its history kept (ADR-0032).
            self._lifecycle.retire_department_memory(caller, removed.department_id)

        return self._change_departments(request, remove)

    def _appoint_department_lead(self, request: Request) -> Response:
        def appoint(member: Member, caller: Caller) -> None:
            asked: DepartmentAppointment = request.state.asked
            department_id = request.path_params["department_id"]
            self._departments.appoint_lead(caller, department_id, asked.member_id)
            self._audit.record(
                DEPARTMENT_LEAD_APPOINTED, member=member, target=department_id, detail={"member_id": asked.member_id}
            )

        return self._change_departments(request, appoint)

    def _remove_department_lead(self, request: Request) -> Response:
        def remove(member: Member, caller: Caller) -> None:
            department_id, member_id = request.path_params["department_id"], request.path_params["member_id"]
            self._departments.remove_lead(caller, department_id, member_id)
            self._audit.record(
                DEPARTMENT_LEAD_REMOVED, member=member, target=department_id, detail={"member_id": member_id}
            )

        return self._change_departments(request, remove)

    def _move_project_in(self, request: Request) -> Response:
        def move(member: Member, caller: Caller) -> None:
            asked: ProjectMove = request.state.asked
            department_id = request.path_params["department_id"]
            self._departments.move_in(caller, department_id, asked.project_id)
            self._audit.record(
                PROJECT_MOVED,
                member=member,
                project_id=asked.project_id,
                target=department_id,
                detail={"department_id": department_id, "from_department_id": None},
            )

        return self._change_departments(request, move)

    def _move_project_out(self, request: Request) -> Response:
        def move(member: Member, caller: Caller) -> None:
            department_id, project_id = request.path_params["department_id"], request.path_params["project_id"]
            self._departments.move_out(caller, department_id, project_id)
            self._audit.record(
                PROJECT_MOVED,
                member=member,
                project_id=project_id,
                target=department_id,
                detail={"department_id": None, "from_department_id": department_id},
            )

        return self._change_departments(request, move)

    def _change_departments(self, request: Request, change: Callable[[Member, Caller], None]) -> Response:
        """Everything an admin or a department lead does to a department: the same guard, and every department as
        it now stands."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            change(member, self._identity.caller_in(member, None))
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return self._departments_now(member)

    def _departments_now(self, member: Member) -> Response:
        answer = Departments(
            departments=[
                DepartmentSummary(
                    department_id=view.department.department_id,
                    name=view.department.name,
                    leads=[ProjectMember(member_id=lead.member_id, name=lead.name) for lead in view.leads],
                    projects=[DepartmentProject(project_id=one.project_id, name=one.name) for one in view.projects],
                    you_lead=view.you_lead,
                    you_may_change=view.you_may_change,
                )
                for view in self._departments.listed(member)
            ],
            you_may_create=member.is_owner or member.is_admin,
        )
        return JSONResponse(answer.model_dump(mode="json"))

    def _repository(self, server_url: str, project_id: str, project_name: str, name: str) -> ProjectRepository:
        files = self._service.connection_files(server_url, project_id, project_name, name)
        return ProjectRepository(name=name, files=[ConnectionFile(**file) for file in files])

    def _detail(self, caller: Caller, path: str) -> MemoryDetail:
        """One memory in full: what it says, its file as Claude reads it, whether it is pinned, and when a coding agent
        last used it. Reading it here is no use of it."""
        memory = self._service.read(caller, path)
        memory["pinned"] = memory["path"] in self._briefing.pinned_paths(caller.company)
        memory["last_used"] = self._uses.last_used(caller.company, memory["path"])
        memory["source"] = self._service.source(caller, path)
        memory["author_name"] = self._names(caller.member).get(memory["author"], memory["author"])
        memory["suspected_instructions"] = reasons_in(memory["title"], memory["summary"], memory["body"])
        against = self._challenging.doubts_against(caller.company, [memory["path"]])[memory["path"]]
        doubts = {each.challenge.id: each for each in against}
        memory["open_challenges"] = [
            _with_evidence(one, doubts.get(one["challenge_id"])) for one in memory["open_challenges"]
        ]
        memory["in_doubt"] = _marked(InDoubt.of(doubts.values()) if doubts else None)
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

    # --- a project's active sessions, read: nothing here changes a session, an activity or a lock (ADR-0009) ---

    def _project_sessions(self, request: Request) -> Response:
        return self._browse(request, self._sessions_now)

    # --- a project's health, read: nothing here pins, decides, retires or uses a memory (ADR-0009) ---

    def _project_health(self, request: Request) -> Response:
        def read(caller: Caller) -> ProjectHealth:
            found = self._health.of(caller)
            names = self._names(caller.member)

            def about(path: str, memory: Memory) -> dict[str, str]:
                return {
                    "path": path,
                    "title": memory.title,
                    "summary": memory.summary,
                    "type": memory.type,
                    "author": memory.author,
                    "author_name": names.get(memory.author, memory.author),
                }

            return ProjectHealth(
                project_id=found.project.project_id,
                project_name=found.project.name,
                outdated_after_days=self._settings.outdated_after_days,
                possibly_outdated=[
                    PossiblyOutdatedMemory(**about(one.path, one.memory), last_used=one.last_used)
                    for one in found.possibly_outdated
                ],
                in_doubt=[
                    DoubtedMemory(**about(one.path, one.memory), in_doubt=_mark(one.in_doubt))
                    for one in found.in_doubt
                ],
            )

        return self._browse(request, read)

    # --- a project's onboarding progress, read: recording it is a session's (ADR-0009) ---

    def _onboarding_progress(self, request: Request) -> Response:
        def read(caller: Caller) -> OnboardingProgress:
            everyone, entries = self._progress.entries(caller)
            names = self._names(caller.member)
            return OnboardingProgress(
                project_id=caller.require_project().project_id,
                everyone=everyone,
                entries=[
                    OnboardingEntry(
                        repository=one.repository,
                        outside_source=one.outside_source,
                        status=one.status,
                        recorded_by=one.recorded_by,
                        recorded_by_name=names.get(one.recorded_by, one.recorded_by),
                        recorded_at=one.recorded_at,
                        promoted=one.promoted,
                        waiting_on_challenge=one.waiting_on_challenge,
                        left_out=one.left_out,
                    )
                    for one in entries
                ],
            )

        return self._browse(request, read)

    # --- a member's reply and answer, through the same operations their session's tools use (ADR-0026) ---

    def _send_message(self, request: Request) -> Response:
        def send(caller: Caller) -> ProjectSessions:
            asked: MessageToSend = request.state.asked
            self._talk.send(caller, asked.to, asked.text)
            return self._sessions_now(caller)

        return self._browse(request, send)

    def _answer_gate(self, request: Request) -> Response:
        def answer(caller: Caller) -> ProjectSessions:
            asked: GateAnswer = request.state.asked
            self._talk.answer(caller, request.path_params["member_id"], asked.answer, asked.text)
            return self._sessions_now(caller)

        return self._browse(request, answer)

    def _sessions_now(self, caller: Caller) -> ProjectSessions:
        """The Sessions page as the caller sees it now. `_browse` placed the caller in the project, which refuses a
        member who can't reach it: none of the reads below checks reach itself."""
        project = caller.require_project()
        held: dict[int, list[HeldLock]] = {}
        for lock in self._locks.held(project.project_id):
            held.setdefault(lock.holder.id, []).append(
                HeldLock(
                    repository=lock.repository,
                    path=lock.path,
                    taken_at=lock.taken_at,
                    last_used_at=lock.last_used_at,
                )
            )
        active = self._activities.in_project(project.project_id)
        collided = self._talk.collided(active)
        gateable = self._talk.can_be_gated(active)
        standing_by = self._talk.standing_by(project.project_id)
        names = self._names(caller.member)
        mine = caller.member_id
        return ProjectSessions(
            project_id=project.project_id,
            project_name=project.name,
            now=self._talk.now(),
            text_limit=TEXT_LIMIT,
            collisions=[
                SessionCollision(
                    later=_named(one.later),
                    earlier=_named(one.earlier),
                    cause=one.collision.cause.value,
                    found_at=one.collision.found_at,
                )
                for one in collided
            ],
            gates=[
                SessionGate(
                    later=_named(gate.later),
                    waits_for=[
                        GateWait(
                            earlier=_named_session(one.earlier, one.activity),
                            until=one.until,
                            refused=one.refused,
                            on_my_work=one.earlier.member_id == mine,
                        )
                        for one in gate.waiting
                    ],
                )
                for gate in self._talk.gated(caller, project.project_id)
            ],
            handoff_notes=[
                SessionHandoffNote(
                    member_id=gone.member_id,
                    member_name=gone.member_name,
                    agent=gone.agent,
                    repository=gone.repository,
                    branch=gone.branch,
                    touched_files=list(gone.touched_files),
                    done=note.done,
                    left=note.left,
                    activity=note.activity,
                    by_server=note.by_server,
                    written_at=note.written_at,
                    last_seen_at=gone.last_seen_at,
                )
                for gone, note in self._talk.handoff_notes(project.project_id)
            ],
            messages=[
                SessionMessage(
                    message_id=one.message_id,
                    sender_member_id=one.sender_member_id,
                    sender_name=one.sender_name,
                    recipient_member_id=one.recipient_member_id,
                    recipient_name=names.get(one.recipient_member_id, one.recipient_member_id),
                    text=one.text,
                    sent_at=one.sent_at,
                    delivered_at=one.delivered_at,
                    sent_by_me=one.sender_member_id == mine,
                    urgent=one.urgent,
                )
                for one in self._talk.messages(project.project_id, mine)
            ],
            sessions=[
                ActiveSession(
                    member_id=each.session.member_id,
                    member_name=each.session.member_name,
                    agent=each.session.agent,
                    repository=each.session.repository,
                    activity=each.activity,
                    from_card=each.from_card,
                    started_at=each.session.started_at,
                    last_seen_at=each.session.last_seen_at,
                    branch=each.session.branch,
                    touched_files=list(each.session.touched_files),
                    locks=held.get(each.session.id, []),
                    can_be_gated=gateable[each.session.id],
                    standby=_standby_of(standing_by.get(each.session.id), names),
                )
                for each in active
            ],
        )

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
                caller, asked.title, asked.description, asked.priority, asked.labels, asked.due_date,
                asked.memories, asked.files,
            )  # fmt: skip
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
                    status=one["status"],
                    path=one.get("path") or one["challenges"],
                    challenge_id=one.get("challenge_id"),
                    reason=one.get("reason"),
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
        pinned = self._briefing.pinned_paths(caller.company)
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
        """Anything done to one memory by its path, placed in the project it lives in (or any, for company memory)."""
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

    def _interviewed(self, request: Request) -> Response:
        """What was written from the member's interviews, in the projects they can still reach. Only a read: retiring
        one is the retire any author has (ADR-0009)."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        promoted = self._audit.interviews_of(member)
        reachable = {project.project_id for project in self._identity.projects(member)}
        theirs = self._explorer.still_authored(
            member.company_code,
            (one.path for one in promoted if _project_in(one.path) is None or _project_in(one.path) in reachable),
            member.member_id,
        )
        names = self._names(member)
        answer = InterviewMemories(
            memories=[
                InterviewMemory(
                    path=one.path,
                    title=theirs[one.path].title,
                    summary=theirs[one.path].summary,
                    level=locate(one.path).level,
                    source=one.source,
                    interviewer=one.interviewer,
                    interviewer_name=names.get(one.interviewer, one.interviewer),
                    interviewed_at=one.at,
                )
                for one in promoted
                if one.path in theirs
            ]
        )
        return JSONResponse(answer.model_dump(mode="json"))

    def _notices(self, request: Request) -> Response:
        """What the member has been told. Only a read: each notice still waits for their next briefing."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        told = self._challenging.told(self._identity.caller_in(member, None), days=NOTICE_DAYS, limit=NOTICE_LIMIT)
        answer = Notices(notices=[Notice(**one, **self._about(member, one["text"])) for one in told])
        return JSONResponse(answer.model_dump(mode="json"))

    def _about(self, member: Member, text: str) -> dict[str, Any]:
        """The board and the card a notice names, where this member can open them."""
        project_id, number = _card_named(text)
        if project_id is None:
            return {"project_id": None, "card": None}
        try:
            caller = self._identity.caller_in(member, project_id)
        except Refused:
            return {"project_id": None, "card": None}
        try:
            card = None if number is None else self._board.card(caller, number)["number"]
        except Refused:
            card = None
        return {"project_id": project_id, "card": card}

    def _decide_challenge(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked: Decision = request.state.asked
        try:
            challenge_id = int(request.path_params["challenge_id"])
        except ValueError:
            return JSONResponse({"message": "That isn't a challenge."}, status_code=422)
        challenge = self._challenging.open_challenge(member.company_code, challenge_id)
        if challenge is None:
            return JSONResponse(
                {"message": f"There is no open challenge {challenge_id} in your company."}, status_code=403
            )
        try:
            result = self._lifecycle.decide_challenge(
                self._working_in(member, project_of(challenge)), challenge_id, asked.decision
            )
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        if result["status"] == "rejected":
            decided = Decided(challenge_id=challenge.id, decision="rejected", in_force=challenge.target_path)
        else:
            decided = Decided(challenge_id=challenge.id, decision="accepted", in_force=result.get("path"))
        left = self._challenge_list(self._identity.caller_in(member, None))
        return JSONResponse(
            DecidedChallenges(waiting=left.waiting, raised=left.raised, decided=decided).model_dump(mode="json")
        )

    def _disputes(self, caller: Caller) -> Response:
        return JSONResponse(self._challenge_list(caller).model_dump(mode="json"))

    def _challenge_list(self, caller: Caller) -> ChallengeList:
        found = self._challenging.waiting_for(caller)
        doubts = {
            doubt.challenge.id: doubt
            for each in self._challenging.doubts_against(caller.company, [one.challenge.target_path for one in found]).values()
            for doubt in each
        }
        waiting = [self._dispute(caller, one, doubts.get(one.challenge.id)) for one in found]
        raised = [
            RaisedChallenge(**one, target_title=self._target(caller, one["kind"], one["foundation"], one["target_path"]).title)
            for one in self._challenging.raised_by(caller)
        ]
        return ChallengeList(waiting=waiting, raised=raised)

    def _dispute(self, caller: Caller, waiting: Waiting, doubt: Doubt | None) -> ChallengeDetail:
        """A challenge waiting for this member, and for a doubt the evidence every raise of it brought."""
        challenge = waiting.challenge
        return ChallengeDetail(
            challenge_id=challenge.id,
            kind=challenge.kind,
            project_id=project_of(challenge),
            raised_by=challenge.raised_by,
            raised_at=challenge.raised_at,
            yours=waiting.decides_as == "author",
            decides_as=waiting.decides_as,
            foundation=challenge.foundation,
            foundation_name=self._foundation_named(challenge),
            target=self._target(caller, challenge.kind, challenge.foundation, challenge.target_path),
            challenger=None if challenge.challenger_path is None else self._side(caller, challenge.challenger_path),
            reasoning=challenge.reasoning,
            reason=challenge.reason,
            evidence=[] if doubt is None else [_evidence(each) for each in doubt.evidence],
            count=None if doubt is None else doubt.count,
        )

    def _foundation_named(self, challenge: Challenge) -> str | None:
        project_id = project_of(challenge)
        if challenge.foundation is None or project_id is None:
            return challenge.foundation
        return self._identity.foundation_name(project_id, challenge.foundation)

    def _target(self, caller: Caller, kind: str, foundation: str | None, path: str) -> ChallengedMemory:
        """What a challenge is against: a memory, or for an "add" the foundation whose folder the path is."""
        if kind != "add" or foundation is None:
            return self._side(caller, path)
        parts = path.split("/")
        name = self._identity.foundation_name(parts[1], foundation) if parts[0] == "projects" else foundation
        return ChallengedMemory(
            path=path, title=name, summary="", body="", level="project", type="", author="", status="foundation"
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

        The console isn't in a project the way a session is, and company memory belongs to none, so anything about
        company memory is done from a project its member can reach.
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
        return self._company(member)

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
            self._sessions.end_all_for(member_id, member.company_pk)
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

    def _rate_limits(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        return JSONResponse(self._rate_limits_answer(member).model_dump(mode="json"))

    def _change_rate_limits(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked: RateLimitChange = request.state.asked
        try:
            self._rate_limits_of.change(
                member, Limits(asked.on, asked.token_per_minute, asked.console_per_minute, asked.address_per_minute)
            )
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return JSONResponse(self._rate_limits_answer(member).model_dump(mode="json"))

    def _license_state(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        return JSONResponse(self._license_answer(member).model_dump(mode="json"))

    def _install_license(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        asked: LicenseKeyText = request.state.asked
        try:
            self._licenses.install(member, asked.key)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return JSONResponse(self._license_answer(member).model_dump(mode="json"))

    def _license_answer(self, member: Member) -> LicenseState:
        current = self._licenses.current()
        held = current.license
        return LicenseState(
            status=current.status,  # type: ignore[arg-type]
            company=held.company if held else None,
            member_cap=held.member_cap if held else None,
            issued=held.issued.isoformat() if held else None,
            expires=held.expires.isoformat() if held else None,
            key_id=held.key_id if held else None,
            days_left=current.days_left,
            stops=current.stops.isoformat() if current.stops else None,
            reason=current.reason,
            source=current.source,  # type: ignore[arg-type]
            you_may_change=member.is_owner or member.is_admin,
        )

    def _rate_limits_answer(self, member: Member) -> RateLimits:
        limits = self._rate_limits_of.limits()
        return RateLimits(
            on=limits.on,
            token_per_minute=limits.token_per_minute,
            console_per_minute=limits.console_per_minute,
            address_per_minute=limits.address_per_minute,
            you_may_change=member.is_owner or member.is_admin,
        )

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
        """Everything an admin does to one member: the same guard, the same answer, the company as it now stands."""
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            change(member, self._identity.caller_in(member, None), request.path_params["member_id"])
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        return self._company(member)

    def _company(self, member: Member) -> Response:
        everyone = Members(
            members=[MemberSummary(**one) for one in self._identity.members(member)],
            member_cap=self._identity.member_cap(),
            members_used=self._identity.members_in_use(),
        )
        return JSONResponse(everyone.model_dump(mode="json"))

    def _reissue_my_token(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        token = self._identity.reissue_own_token(member)
        self._audit.record(TOKEN_ISSUED, member=member, target=member.member_id, detail={"for": "themselves"})
        return self._issued(request, member.member_id, token)

    # A member's time zone is a member setting, not a memory write (ADR-0009). Each call acts on the signed-in member
    # alone: none names a member, so no member can change another's.

    def _my_time_zone(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        kept = self._identity.time_zone(member.pk)
        choices = YourTimeZoneChoices(chosen=kept.chosen, detected=kept.detected, time_zones=list(time_zone.names()))
        return JSONResponse(choices.model_dump(mode="json"))

    def _choose_my_time_zone(self, request: Request) -> Response:
        asked: ChosenTimeZone = request.state.asked
        return self._on_own_time_zone(request, lambda member: self._identity.choose_time_zone(member, asked.time_zone))

    def _report_my_time_zone(self, request: Request) -> Response:
        asked: DetectedTimeZone = request.state.asked
        return self._on_own_time_zone(request, lambda member: self._identity.detect_time_zone(member, asked.time_zone))

    def _on_own_time_zone(self, request: Request, change: Callable[[Member], MemberTimeZone]) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            kept = change(member)
        except NotATimeZone as refused:
            return JSONResponse({"message": str(refused)}, status_code=422)
        return JSONResponse(YourTimeZone(chosen=kept.chosen, detected=kept.detected).model_dump(mode="json"))

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
        titles = self._explorer.titles(
            member.company_code, (event.target for event in page.events if event.target and event.target.endswith(".md"))
        )
        answer = AuditPage(
            events=[AuditEvent(**vars(event), title=titles.get(event.target or "")) for event in page.events],
            next=page.next,
        )
        return JSONResponse(answer.model_dump(mode="json"))

    def _export(self, request: Request) -> Response:
        member = self._member(request)
        if member is None:
            return _sign_in_first()
        try:
            package = self._export_of.build(member)
        except Refused as refused:
            return JSONResponse({"message": str(refused)}, status_code=403)
        self._audit.record(COMPANY_EXPORTED, member=member, detail={"bytes": len(package)})
        name = f"{member.company_code}-shared-memory-export.zip"
        return Response(
            package, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )

    def _sign_out(self, request: Request) -> Response:
        self._sessions.end(request.cookies.get(COOKIE))
        signed_out = JSONResponse(self._describe(None, request).model_dump(mode="json"))
        signed_out.delete_cookie(COOKIE, path="/", httponly=True, secure=self._https(request), samesite="lax")
        return signed_out

    # --- shared bits ---

    def _member(self, request: Request) -> Member | None:
        return self._sessions.member_for(request.cookies.get(COOKIE))

    def _describe(self, member: Member | None, request: Request) -> Status:
        return Status(
            signed_in=member is not None,
            github_sign_in=self._sessions.configured,
            hosted=self._settings.signs_in_through_platform,
            server_url=self._server_url(request),
            platform_url=self._settings.platform_url.rstrip("/") or None,
            member=None
            if member is None
            else SignedInMember(
                member_id=member.member_id,
                name=member.name,
                company=member.company_code,
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
