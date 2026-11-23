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

from pydantic import BaseModel, Field

from shared_memory.audit import Kind
from shared_memory.challenges import DecidesAs, Reason
from shared_memory.messages import TEXT_LIMIT
from shared_memory.ratelimit import MAX_PER_MINUTE, MIN_PER_MINUTE

PREFIX = "/api"


class SignedInMember(BaseModel):
    """Who the console is signed in as."""

    member_id: str
    name: str
    # The company the member is in (ADR-0031).
    company: str
    role: Literal["owner", "admin", "member"]
    leads_a_project: bool


class Status(BaseModel):
    """Whether the console has reached the server, and who it is signed in as."""

    signed_in: bool
    github_sign_in: bool
    # Whether this is a hosted server, whose members the platform signs in: what setting up sign-in takes differs.
    hosted: bool
    member: SignedInMember | None
    # The address every coding agent reaches this server at: the one the repository's files name.
    server_url: str
    # The platform's address, where the landing page, the plans, the Terms and the Privacy Policy live: the console links
    # there. None on a server that wasn't given one.
    platform_url: str | None


class AuditEvent(BaseModel):
    """One thing that happened, and who did it."""

    id: int
    at: datetime
    actor: str
    kind: Kind
    project_id: str | None
    target: str | None
    # A memory's title as it is now, read from the memory when the log is asked for: the log itself keeps only where
    # the memory is. None for anything that isn't a memory, and for a memory no longer at that path.
    title: str | None
    detail: dict[str, Any]


class AuditPage(BaseModel):
    """A page of the audit log, newest first, with where the next page starts."""

    events: list[AuditEvent]
    next: int | None


class RateLimits(BaseModel):
    """The server's rate limit: whether it is on, and how many calls a minute each kind of caller may make."""

    on: bool
    token_per_minute: int
    console_per_minute: int
    address_per_minute: int
    # Whether the signed-in member may change them: the company's owner and its admins.
    you_may_change: bool


class RateLimitChange(BaseModel):
    """What an admin sets the rate limit to."""

    on: bool
    token_per_minute: int = Field(ge=MIN_PER_MINUTE, le=MAX_PER_MINUTE)
    console_per_minute: int = Field(ge=MIN_PER_MINUTE, le=MAX_PER_MINUTE)
    address_per_minute: int = Field(ge=MIN_PER_MINUTE, le=MAX_PER_MINUTE)


class LicenseState(BaseModel):
    """The server's license: whether it is licensed, expiring, lapsed, read-only (a hosted server's key has lapsed),
    unlicensed (no key) or invalid (a key that can't be trusted), and what a trusted key says. Nothing here ever
    includes the key itself."""

    status: Literal["licensed", "expiring", "lapsed", "read-only", "unlicensed", "invalid"]
    # The company the key is for (ADR-0031).
    company: str | None
    member_cap: int | None
    issued: str | None
    expires: str | None
    key_id: str | None
    days_left: int | None
    # The day a read-only hosted server will be stopped, fourteen days after its key lapsed (ADR-0022); otherwise null.
    stops: str | None
    # Why there is no trusted key, in words an admin can act on.
    reason: str | None
    # Where the key came from: installed in the console, or set in the server's environment.
    source: Literal["console", "environment"] | None
    # Whether the signed-in member may install a key: the company's owner and its admins.
    you_may_change: bool


class LicenseKeyText(BaseModel):
    """A license key being installed."""

    key: str = Field(max_length=4000)


class ProjectMember(BaseModel):
    """A member named on a project."""

    member_id: str
    name: str


class DepartmentRef(BaseModel):
    """The department a project is in (ADR-0032)."""

    department_id: str
    name: str
    # Closed to its access list: the project then reaches no one outside the department, and is never opened wider.
    restricted: bool


class ProjectSummary(BaseModel):
    """A project the member can reach, who looks after it, and the department it is in, if any."""

    project_id: str
    name: str
    restricted: bool
    leads: list[ProjectMember]
    you_lead: bool
    department: DepartmentRef | None


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


class ProjectFoundation(BaseModel):
    """One of a project's foundations, whether it is one of the core four, and the members who keep it."""

    slug: str
    name: str
    core: bool
    keepers: list[ProjectMember]


class ProjectDetail(BaseModel):
    """One project: who leads it, who is allowed in, which repositories belong to it, and what may be changed."""

    project_id: str
    name: str
    restricted: bool
    leads: list[ProjectMember]
    foundations: list[ProjectFoundation]
    access: list[ProjectMember]
    repositories: list[ProjectRepository]
    you_lead: bool
    you_may_change: bool
    # The department the project is in, or None for a project in none (ADR-0032).
    department: DepartmentRef | None


class ProjectName(BaseModel):
    """What a project is called."""

    name: str


class Appointment(BaseModel):
    """The member being made a lead of this project."""

    member_id: str


class FoundationName(BaseModel):
    """What an extra foundation is called; its folder is the slug of the name."""

    name: str


class KeeperAssignment(BaseModel):
    """The member being made a keeper of a foundation."""

    member_id: str


class RepositoryName(BaseModel):
    """A repository's short name, unique within its project."""

    name: str


class Restriction(BaseModel):
    """Whether this project is closed to its access list, or open to the whole company."""

    restricted: bool


class AccessChange(BaseModel):
    """The member being let into this project."""

    member_id: str


class DepartmentProject(BaseModel):
    """A project in a department."""

    project_id: str
    name: str


class DepartmentSummary(BaseModel):
    """A department (ADR-0032): its department leads, the projects in it this member can reach, whether it is
    restricted and who is on its access list, and what they may change."""

    department_id: str
    name: str
    leads: list[ProjectMember]
    projects: list[DepartmentProject]
    you_lead: bool
    you_may_change: bool
    # Restricted, its department memory and projects are invisible to everyone but its access list, its leads and the
    # company's admins. The access list is kept while it is open, so restricting it again lets the same members back.
    restricted: bool
    access: list[ProjectMember]


class Departments(BaseModel):
    """Every department of the company, by name, and whether this member may create one."""

    departments: list[DepartmentSummary]
    you_may_create: bool


class DepartmentMemoryEntry(BaseModel):
    """One active department memory, as the department page lists it: no author, so the page names no member."""

    path: str
    title: str
    summary: str
    type: str


class MemoryCounts(BaseModel):
    """How one area's memory is doing, as counts only: its active memories, how many are possibly outdated, how many a
    coding agent recalled or read within the window (saving one counts too, as it starts its clock again), and the
    level contradictions and other challenges waiting on it."""

    memories: int
    possibly_outdated: int
    used: int
    level_contradictions: int
    challenges: int


class ProjectRollUp(BaseModel):
    """One project of the department, with its counts."""

    project_id: str
    name: str
    counts: MemoryCounts


class DepartmentRollUp(BaseModel):
    """How memory is doing across a department (spec #624), never per member: each project the member can reach, and
    department memory's own use. window_days is how far back `used` counts; outdated_after_days is the server's
    setting."""

    window_days: int
    outdated_after_days: float
    projects: list[ProjectRollUp]
    department_memory: MemoryCounts


class DepartmentPage(BaseModel):
    """A department's page (#636): the projects in it this member can reach and its department memory, and for its
    department leads and the company's admins the roll-up, which is None for anyone else. Reading it changes nothing."""

    department_id: str
    name: str
    restricted: bool
    you_lead: bool
    projects: list[DepartmentProject]
    memory: list[DepartmentMemoryEntry]
    roll_up: DepartmentRollUp | None


class DepartmentName(BaseModel):
    """What a department is called."""

    name: str


class DepartmentAppointment(BaseModel):
    """The member being made a lead of this department."""

    member_id: str


class DepartmentRestriction(BaseModel):
    """Whether this department is closed to its access list, or open to the whole company."""

    restricted: bool


class DepartmentAccessChange(BaseModel):
    """The member being put on this department's access list."""

    member_id: str


class ProjectMove(BaseModel):
    """The project being moved into this department."""

    project_id: str


class PendingChallenge(BaseModel):
    """A challenge this personal memory is waiting on."""

    challenge_id: int
    kind: str
    replaces: str | None


class DoubtEvidence(BaseModel):
    """What one member who raised a doubt brought: their reasoning and, for contradicts_code, the line of code they
    quote, written repository:path:line, as the code has it."""

    member_id: str
    reasoning: str | None
    code_reference: str | None
    quoted_line: str | None
    raised_at: datetime


class OpenChallenge(BaseModel):
    """A challenge raised against this memory."""

    challenge_id: int
    kind: str
    raised_by: str
    challenger_path: str | None
    # The reason it names when it doubts the memory (CONTEXT.md: Reason); none for a supersede or a retire.
    reason: Reason | None
    # Whether the member reading this may decide it, and in what capacity: as its author, as a lead of its project, as
    # an admin, or as anyone may once the fallback has passed or its author has left.
    may_decide: bool
    decides_as: DecidesAs | None
    # For a doubt, shown to every member who can read the memory, deciders or not: how many members raised it and the
    # evidence each raise brought, the first raiser's first. A challenge that names no reason has neither.
    count: int | None
    evidence: list[DoubtEvidence]


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


class InDoubtReason(BaseModel):
    """One reason a memory is in doubt for: how many members name it and, for contradicts_code, where the code is."""

    reason: Reason
    count: int
    # Each code reference quoted for it, written repository:path:line, first quoted first and each once.
    code_references: list[str]


class InDoubtMark(BaseModel):
    """What marks a memory in doubt (CONTEXT.md): how many members doubt it, for which reasons, and the in-doubt line
    a session is shown, which the console shows as it is."""

    count: int
    reasons: list[InDoubtReason]
    line: str


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
    # Whether the challenged memory is this member's own, and in what capacity the challenge is theirs to decide.
    yours: bool
    decides_as: DecidesAs
    # The foundation (slug and name) the challenge is about, when it is one. An "add" challenge has no challenged
    # memory: its target stands for the foundation, and the challenger is the memory to add.
    foundation: str | None
    foundation_name: str | None
    target: ChallengedMemory
    challenger: ChallengedMemory | None
    # Why the member who raised it believes the memory should go, when they said. The console shows it, never edits it.
    reasoning: str | None
    # For a doubt: the reason it names, every raise's evidence (the first raiser's first) and how many raises it has
    # had: how many members, the first and each +1. A challenge that names no reason has none of them.
    reason: Reason | None
    evidence: list[DoubtEvidence]
    count: int | None


class RaisedChallenge(BaseModel):
    """A challenge this member raised, and how it ended."""

    challenge_id: int
    kind: str
    # The reason a doubt names; none for any other kind.
    reason: Reason | None
    target_path: str
    target_title: str
    challenger_path: str | None
    foundation: str | None
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
    """Accept a challenge or reject it; a level contradiction is decided by keeping an exception, with a reason, or by
    following the broader memory, which retires the narrower one."""

    decision: Literal["accept", "reject", "keep_exception", "follow"]
    reason: str | None = None


class Decided(BaseModel):
    """What deciding a challenge did."""

    challenge_id: int
    decision: Literal["accepted", "rejected", "kept_exception", "followed"]
    # The memory in force now: the one offered in its place, at the path promoting it gave it, when a supersede was
    # accepted; the challenged memory when the challenge was rejected; none when a retire was accepted. For a level
    # contradiction, the narrower memory when an exception was kept, the broader one when it was followed.
    in_force: str | None


class DecidedChallenges(ChallengeList):
    """What deciding a challenge did, and what is still waiting for this member's decision."""

    decided: Decided


class Retired(BaseModel):
    """What retiring did: the memory is retired, or its author has been asked to retire it. A known issue that a
    card moved to Done could not retire is not_retired, with the reason."""

    status: str
    path: str
    challenge_id: int | None
    reason: str | None = None


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
    # Why its lead keeps it as an exception to exception_to, once a level contradiction is decided that way.
    exception_reason: str | None = None
    tied_files: list[str]
    promoted_by: str | None
    imported_by: str | None
    imported_from: str | None
    body: str
    author_name: str
    source: str
    pinned: bool
    # No coding agent has recalled or read it for `outdated_after_days`, and it isn't pinned (CONTEXT.md: Outdated
    # memory). last_used is when one last did, or when it was last saved; null for a memory the server has no use of.
    possibly_outdated: bool
    last_used: datetime | None
    # Why the text reads like orders to a coding agent (CONTEXT.md: Suspected instructions); empty when it doesn't.
    # Worked out from the text each time, so the console only shows it: it never clears or writes it (ADR-0009).
    suspected_instructions: list[str]
    pending: list[PendingChallenge]
    open_challenges: list[OpenChallenge]
    # The memory is in doubt: what its open doubts say, which the console shows and never clears (ADR-0009). None when
    # nobody doubts it.
    in_doubt: InDoubtMark | None


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
    # The section that matched has the words searched for, as written or in another form of the same word. False is a
    # match by meaning alone: among the closest there are, but weaker, since nothing in it says it in those words.
    words_match: bool


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
    possibly_outdated: bool
    suspected_instructions: list[str]


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
    """One folder of the company's memory: where it sits, the folders in it, and its memories."""

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
    """One member of the company, as an admin sees them."""

    member_id: str
    name: str
    role: Literal["owner", "admin", "member"]
    github_login: str | None
    # Only admins and the owner are told these two (a member sees null and an empty list): they are the company's
    # to govern, not every member's to read.
    verified_email: str | None
    # The email an admin or setup typed, not yet proven by its holder; hidden from members like the verified one.
    added_email: str | None
    sign_in_methods: list[Literal["github"]]
    removed: bool


class Members(BaseModel):
    members: list[MemberSummary]
    # The server's member cap and how many places are taken (removed members hold none); no cap: null.
    member_cap: int | None
    members_used: int


class NewMember(BaseModel):
    """A member being added to the company."""

    member_id: str
    name: str
    # Their GitHub username or their email, not both.
    github: str | None = None
    email: str | None = None


class ChangedMember(BaseModel):
    """What to correct about a member. Anything left out stays as it was."""

    name: str | None = None
    github: str | None = None
    # Left out: unchanged. Empty: cleared. Otherwise the new email, unverified until its holder proves it.
    email: str | None = None


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


class YourTimeZone(BaseModel):
    """The signed-in member's time zone: the one they chose, and the one detected from their browser. Times are shown
    in the chosen one, else the detected one. Each is an IANA name, or None until set."""

    chosen: str | None
    detected: str | None


class YourTimeZoneChoices(YourTimeZone):
    """The signed-in member's time zone, and every time zone they can choose from."""

    time_zones: list[str]


class ChosenTimeZone(BaseModel):
    """The time zone a member chooses, or None to have it detected from their browser."""

    time_zone: str | None


class DetectedTimeZone(BaseModel):
    """The time zone the member's browser is set to."""

    time_zone: str


Column = Literal["to_do", "doing", "blocked", "done"]
Priority = Literal["high", "normal", "low"]


class CardComment(BaseModel):
    """A remark on a card, and who made it."""

    author: str
    author_name: str
    text: str
    created_at: datetime


class Card(BaseModel):
    """One piece of work on a board, known by its number within the project. Memories and known issues are linked by
    path, files as repository:path. waits_on is the number of the card a blocked card waits on."""

    number: int
    title: str
    description: str
    column: Column
    position: int
    priority: Priority
    labels: list[str]
    due_date: str | None
    creator: str
    creator_name: str
    assignee: str | None
    assignee_name: str | None
    blocked_reason: str | None
    waits_on: int | None
    memories: list[str]
    files: list[str]
    known_issues: list[str]
    comments: list[CardComment]
    created_at: datetime
    updated_at: datetime
    moved_at: datetime


class CardDetail(Card):
    """A card whole, with the titles of the memories and known issues it links to that the member can read."""

    titles: dict[str, str]


class BoardColumn(BaseModel):
    """One of a board's four columns, its cards top first."""

    column: Column
    name: str
    cards: list[Card]


class ProjectBoard(BaseModel):
    """A project's board: To do, Doing, Blocked and Done, and every label already on it."""

    project_id: str
    project_name: str
    columns: list[BoardColumn]
    labels: list[str]


class BoardArchive(BaseModel):
    """Cards done more than 14 days ago, which have left the board: the most recently done first."""

    project_id: str
    project_name: str
    cards: list[Card]


class MovedCard(CardDetail):
    """A card where it now is. One that has just entered Done says what became of each still-active known issue it
    was to fix: retired, or its author asked to retire it by a challenge."""

    known_issues_fixed: list[Retired]


class NewCard(BaseModel):
    """A card to add at the bottom of To do. Labels already on the board are the ones to reuse; a due date is written
    YYYY-MM-DD. It may link to memories, by path, and to files, each written repository:path."""

    title: str
    description: str = ""
    priority: Priority | None = None
    labels: list[str] = Field(default_factory=list)
    due_date: str | None = None
    memories: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class CardFields(BaseModel):
    """What to change about a card: only the fields given change. An empty due date or assignee takes it off; only a
    card's assignee, the project's leads and the company's admins give it an assignee. Memories and files, when given,
    replace the card's links of that kind: memories by path, files as repository:path."""

    title: str | None = None
    description: str | None = None
    priority: Priority | None = None
    labels: list[str] | None = None
    due_date: str | None = None
    assignee: str | None = None
    memories: list[str] | None = None
    files: list[str] | None = None


class CardMove(BaseModel):
    """Where a card goes: a column, and a position in it (1 is the top; without one it goes to the bottom). A card
    goes to Blocked only with a blocked_reason, and may name the card it waits on."""

    column: Column
    position: int | None = Field(default=None, ge=1)
    blocked_reason: str | None = None
    waits_on: int | None = Field(default=None, ge=1)


class CardCommentText(BaseModel):
    """A comment to add to a card."""

    text: str


class DeletedCard(BaseModel):
    """The number of the card that was deleted, which is not used again."""

    number: int


class HeldLock(BaseModel):
    """A file a session holds a lock on: its repository, and its path from that repository's root."""

    repository: str
    path: str
    taken_at: datetime
    last_used_at: datetime


class AwaitedMember(BaseModel):
    """A member whose answer a standing-by session awaits."""

    member_id: str
    member_name: str


class SessionStandby(BaseModel):
    """A session standing by (ADR-0027): its coding agent waits for news without its member typing. awaits names the
    members whose answer it awaits, as it was when the standby started: the earlier members its edit is gated on, those
    its urgent messages not yet answered went to, and the member its latest message went to until they reply. It is
    empty for a standby that awaits no member in particular. ends_at is when it ends with nothing yet, by the
    server's clock, unless news, a newer standby or the member's next prompt ends it first."""

    started_at: datetime
    ends_at: datetime
    awaits: list[AwaitedMember]


class ActiveSession(BaseModel):
    """One active session of a member's coding agent. agent is None until the session has said which coding agent it
    runs in, and repository is None for a session whose connection names none. activity is what the session stated;
    for a session that stated none it is the title of its member's card in Doing, and from_card says so; None when
    there is neither. last_seen_at is when the session last called the server. branch is its git branch as its hook
    before a tool last named it, None until one has; touched_files are the files its tool calls named, each a path
    from its repository's root, the most recent first. Neither the tools it called nor its prompts are ever shown.
    can_be_gated is False for a session in a coding agent that has no hooks (Copilot in VS Code, Cursor on Windows):
    nothing refuses its edits, so a gate on it is only guidance. It is known once a tool call has reported the agent
    and no hook of the session has called. standby is the session's standby while it stands by, None otherwise."""

    member_id: str
    member_name: str
    agent: str | None
    repository: str | None
    activity: str | None
    from_card: bool
    started_at: datetime
    last_seen_at: datetime
    branch: str | None
    touched_files: list[str]
    locks: list[HeldLock]
    can_be_gated: bool
    standby: SessionStandby | None


class NamedSession(BaseModel):
    """An active session as a collision, a gate or a message names it: its member, its coding agent (None until it has
    said which) and its activity (None when it has none). session_number tells it apart from the same member's other
    sessions, so the page can tell two gates between the same two members apart; it is not the identifier its coding
    agent sends, which never leaves its member (ADR-0018)."""

    session_number: int
    member_id: str
    member_name: str
    agent: str | None
    activity: str | None


class SessionCollision(BaseModel):
    """Two active sessions found working on nearly the same thing. later is the session whose prompt or activity made
    the collision, as cause says; earlier is the other. found_at is when it was found. The prompt is never shown."""

    later: NamedSession
    earlier: NamedSession
    cause: Literal["prompt", "activity"]
    found_at: datetime


class GateWait(BaseModel):
    """One earlier session a gate waits for, until the project's wait has passed (until), unless its member agrees.
    refused says its member refused: the gate then holds past until, while that session stays active. on_my_work says
    the earlier session is the signed-in member's, so they may agree or refuse from the console."""

    earlier: NamedSession
    until: datetime
    refused: bool
    on_my_work: bool


class SessionGate(BaseModel):
    """A later session whose file edits on colliding work are refused now, and the earlier sessions it waits for: the
    gate stops waiting for each when the project's wait has passed, or at once when its member says it is different
    work. The page counts the time left down from now (the server's clock when it answered) to each until."""

    later: NamedSession
    waits_for: list[GateWait]


class SessionMessage(BaseModel):
    """A message the signed-in member's sessions in the project sent or were sent, still kept: who sent it and who it is
    for, by member ID and name, its text, when it was sent, and when a session of its recipient's was first told of it
    (None while it waits). sent_by_me says it came from one of the signed-in member's sessions. message_id tells it
apart from every other message. urgent says it gates the recipient's session on the colliding work until their member
answers it, which a reply does."""

    message_id: int
    sender_member_id: str
    sender_name: str
    recipient_member_id: str
    recipient_name: str
    text: str
    sent_at: datetime
    delivered_at: datetime | None
    sent_by_me: bool
    urgent: bool


class MessageToSend(BaseModel):
    """A message from the signed-in member's session in the project to another member's sessions there, such as a
    reply: the member it is for, by member ID, and its text, at most text_limit characters."""

    to: str
    text: str = Field(max_length=TEXT_LIMIT)


class GateAnswer(BaseModel):
    """The signed-in member's answer to a gate on their session's work, and their words for the gated member, if any,
    at most text_limit characters."""

    answer: Literal["agree", "refuse"]
    text: str | None = Field(default=None, max_length=TEXT_LIMIT)


class SessionHandoffNote(BaseModel):
    """The handoff note of a session in the project that ended or went idle within the recent-work window (#515): whose
    session it was, in which coding agent and repository, on which branch and with which files touched, what is done
    and what is left, the activity it was written beside, whether the server put it together because the session left
    none, and when it was written. Notes are written only by sessions or the server, never here (ADR-0026)."""

    member_id: str
    member_name: str
    agent: str | None
    repository: str | None
    branch: str | None
    touched_files: list[str]
    done: str
    left: str
    activity: str | None
    by_server: bool
    written_at: datetime
    last_seen_at: datetime


class PossiblyOutdatedMemory(BaseModel):
    """A memory on project health's possibly outdated list: no coding agent has recalled or read it for
    `outdated_after_days`, and it isn't pinned. last_used is when one last did, or when it was last saved."""

    path: str
    title: str
    summary: str
    type: str
    author: str
    author_name: str
    last_used: datetime | None


class DoubtedMemory(BaseModel):
    """A memory on project health's in-doubt list, with what marks it so. Its open doubts are decided on the
    challenges screen, never here (ADR-0009)."""

    path: str
    title: str
    summary: str
    type: str
    author: str
    author_name: str
    in_doubt: InDoubtMark


class ProjectHealth(BaseModel):
    """A project's health now (CONTEXT.md: Project health), for its leads and the company's admins: its project memory
    that is possibly outdated, the longest unused first, and its memory in doubt, the most doubted first. Read-only:
    reading it is no use of any memory and changes nothing. outdated_after_days is the server's setting."""

    project_id: str
    project_name: str
    outdated_after_days: float
    possibly_outdated: list[PossiblyOutdatedMemory]
    in_doubt: list[DoubtedMemory]


class OnboardingEntry(BaseModel):
    """How far onboarding has got for one repository or one kind of outside source (wiki, ticket, pr-comment or
    interview): exactly one of repository and outside_source is set. status is not_started, partly_done or done, as a
    session last recorded it, by whom and when. promoted and waiting_on_challenge count the imports from it in the
    audit log: promoted, and promoted into a challenge no one has decided yet. left_out is what the session said it
    left out."""

    repository: str | None
    outside_source: str | None
    status: str
    recorded_by: str
    recorded_by_name: str
    recorded_at: datetime
    promoted: int
    waiting_on_challenge: int
    left_out: int


class OnboardingProgress(BaseModel):
    """A project's onboarding progress, repositories first. everyone says whether these are all its entries, as its
    leads and the company's admins see them, or only the ones the signed-in member recorded. Read-only: a session
    records progress."""

    project_id: str
    everyone: bool
    entries: list[OnboardingEntry]


class InterviewMemory(BaseModel):
    """A memory written from the signed-in member's interview, which they author (ADR-0029): where it is, what it says
    in brief, its level, the interview it came from (source), and who ran the interview and when its memory was
    promoted."""

    path: str
    title: str
    summary: str
    level: str
    source: str
    interviewer: str
    interviewer_name: str
    interviewed_at: datetime


class InterviewMemories(BaseModel):
    """Every memory written from the signed-in member's interviews that is still active and theirs, newest first. They
    may retire any of it, with the same retire as any memory they author; nothing here edits one."""

    memories: list[InterviewMemory]


class ProjectSessions(BaseModel):
    """A project's active sessions, the oldest first, each with the files it holds a lock on. A session that has ended
    or gone idle is not among them. With them, what every member who can reach the project sees: its collisions and its
    gates, the oldest first; the handoff notes of its sessions gone lately, the most recently seen first; and what only
    the signed-in member sees: their own sessions' messages, the oldest first.
    now is the server's clock when it answered. The page asks again every few seconds; asking changes no session and
    delivers no message. text_limit is the most characters a reply or an answer's words may have."""

    project_id: str
    project_name: str
    now: datetime
    text_limit: int
    sessions: list[ActiveSession]
    collisions: list[SessionCollision]
    gates: list[SessionGate]
    handoff_notes: list[SessionHandoffNote]
    messages: list[SessionMessage]


class Notice(BaseModel):
    """Something the member was told, as their briefing words it. One about a card names its project, and the card's
    number while the card is still there to open."""

    notice_id: int
    text: str
    created_at: datetime
    project_id: str | None
    card: int | None


class Notices(BaseModel):
    """What the member has been told, newest first: every notice still waiting for their next session, and the last
    week's that a session has already had."""

    notices: list[Notice]


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
    # The media type of a file the call streams instead of JSON; such a call answers `None`.
    download: str | None = None


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
        summary="Begin signing in: send the member to GitHub, or to the platform on a hosted server.",
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
        path="/sign-in/platform/callback",
        method="GET",
        operation_id="sign_in_handed_over",
        summary="Finish a sign-in the platform handed over, on a hosted server, and return the member to the console.",
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
        path="/projects/{project_id}/foundations",
        method="POST",
        operation_id="add_foundation",
        summary="Add an extra foundation to this project, beside the core four.",
        answers=ProjectDetail,
        changes=True,
        accepts=FoundationName,
    ),
    Declaration(
        path="/projects/{project_id}/foundations/{foundation}/remove",
        method="POST",
        operation_id="remove_foundation",
        summary="Remove an extra foundation of this project once it holds no active memory.",
        answers=ProjectDetail,
        changes=True,
    ),
    Declaration(
        path="/projects/{project_id}/foundations/{foundation}/keepers",
        method="POST",
        operation_id="assign_keeper",
        summary="Make a member a keeper of one of this project's foundations.",
        answers=ProjectDetail,
        changes=True,
        accepts=KeeperAssignment,
    ),
    Declaration(
        path="/projects/{project_id}/foundations/{foundation}/keepers/{member_id}/remove",
        method="POST",
        operation_id="remove_keeper",
        summary="Take a keeper off one of this project's foundations.",
        answers=ProjectDetail,
        changes=True,
    ),
    Declaration(
        path="/departments",
        method="GET",
        operation_id="departments",
        summary="Every department of the company, with its leads and the projects in it this member can reach.",
        answers=Departments,
    ),
    Declaration(
        path="/departments/{department_id}",
        method="GET",
        operation_id="department",
        summary=(
            "A department's page: its projects and department memory, and for its leads and the company's admins a "
            "roll-up of each project's counts and department memory's use, never per member. Changes nothing."
        ),
        answers=DepartmentPage,
    ),
    Declaration(
        path="/departments",
        method="POST",
        operation_id="create_department",
        summary="Create a department with no leads and no projects. Only the company's admins can.",
        answers=Departments,
        changes=True,
        accepts=DepartmentName,
    ),
    Declaration(
        path="/departments/{department_id}/rename",
        method="POST",
        operation_id="rename_department",
        summary="Change a department's name. Its department ID stays as it is.",
        answers=Departments,
        changes=True,
        accepts=DepartmentName,
    ),
    Declaration(
        path="/departments/{department_id}/remove",
        method="POST",
        operation_id="remove_department",
        summary="Remove a department, leaving its projects in no department.",
        answers=Departments,
        changes=True,
    ),
    Declaration(
        path="/departments/{department_id}/leads",
        method="POST",
        operation_id="appoint_department_lead",
        summary="Make a member a lead of this department.",
        answers=Departments,
        changes=True,
        accepts=DepartmentAppointment,
    ),
    Declaration(
        path="/departments/{department_id}/leads/{member_id}/remove",
        method="POST",
        operation_id="remove_department_lead",
        summary="Take a lead off this department.",
        answers=Departments,
        changes=True,
    ),
    Declaration(
        path="/departments/{department_id}/projects",
        method="POST",
        operation_id="move_project_in",
        summary="Move a project in no department into this one.",
        answers=Departments,
        changes=True,
        accepts=ProjectMove,
    ),
    Declaration(
        path="/departments/{department_id}/projects/{project_id}/remove",
        method="POST",
        operation_id="move_project_out",
        summary="Move a project out of this department, leaving it in no department.",
        answers=Departments,
        changes=True,
    ),
    Declaration(
        path="/departments/{department_id}/restrict",
        method="POST",
        operation_id="restrict_department",
        summary="Close a department to its access list, or open it to the whole company again.",
        answers=Departments,
        changes=True,
        accepts=DepartmentRestriction,
    ),
    Declaration(
        path="/departments/{department_id}/access",
        method="POST",
        operation_id="grant_department_access",
        summary="Put a member on a department's access list.",
        answers=Departments,
        changes=True,
        accepts=DepartmentAccessChange,
    ),
    Declaration(
        path="/departments/{department_id}/access/{member_id}/remove",
        method="POST",
        operation_id="revoke_department_access",
        summary="Take a member off a department's access list.",
        answers=Departments,
        changes=True,
    ),
    Declaration(
        path="/projects/{project_id}/restrict",
        method="POST",
        operation_id="restrict_project",
        summary="Close a project to its access list, or open it to the whole company again.",
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
        path="/projects/{project_id}/board",
        method="GET",
        operation_id="board",
        summary="A project's board, column by column, narrowed by assignee (a member ID), label and priority.",
        answers=ProjectBoard,
        query=("assignee", "label", "priority"),
    ),
    Declaration(
        path="/projects/{project_id}/board/archive",
        method="GET",
        operation_id="board_archive",
        summary="The cards that have left a project's board, done more than 14 days ago, under the board's filters.",
        answers=BoardArchive,
        query=("assignee", "label", "priority"),
    ),
    Declaration(
        path="/projects/{project_id}/health",
        method="GET",
        operation_id="project_health",
        summary=(
            "A project's health, for its leads and the company's admins: its possibly outdated memory and its memory in "
            "doubt, with each one's count and reasons. Changes nothing."
        ),
        answers=ProjectHealth,
    ),
    Declaration(
        path="/projects/{project_id}/onboarding",
        method="GET",
        operation_id="onboarding_progress",
        summary=(
            "A project's onboarding progress per repository and outside source: status, who recorded it and when, and "
            "how many imports were promoted, wait on a challenge or were left out. Leads and admins see every entry; "
            "any other member sees their own. Changes nothing."
        ),
        answers=OnboardingProgress,
    ),
    Declaration(
        path="/projects/{project_id}/sessions",
        method="GET",
        operation_id="project_sessions",
        summary=(
            "A project's active sessions: whose each is, its coding agent, its activity and the files it holds; the "
            "project's collisions and gates; and the signed-in member's own sessions' messages."
        ),
        answers=ProjectSessions,
    ),
    Declaration(
        path="/projects/{project_id}/sessions/messages",
        method="POST",
        operation_id="send_message",
        summary=(
            "Send a message, such as a reply, from the signed-in member's session in the project to another member's "
            "sessions there, which hear it on their next tool call or prompt."
        ),
        answers=ProjectSessions,
        changes=True,
        accepts=MessageToSend,
    ),
    Declaration(
        path="/projects/{project_id}/sessions/gates/{member_id}/answer",
        method="POST",
        operation_id="answer_gate",
        summary=(
            "Agree to or refuse the gate a member's session has on the signed-in member's session's work; the gated "
            "session hears it on its next tool call or prompt."
        ),
        answers=ProjectSessions,
        changes=True,
        accepts=GateAnswer,
    ),
    Declaration(
        path="/projects/{project_id}/cards/{number}",
        method="GET",
        operation_id="card",
        summary="One card on a project's board or in its archive, with its links and comments.",
        answers=CardDetail,
    ),
    Declaration(
        path="/projects/{project_id}/cards",
        method="POST",
        operation_id="add_card",
        summary="Add a card to the bottom of To do on a project's board, numbered next in the project.",
        answers=CardDetail,
        changes=True,
        accepts=NewCard,
    ),
    Declaration(
        path="/projects/{project_id}/cards/{number}",
        method="POST",
        operation_id="edit_card",
        summary="Change a card's title, description, priority, labels, due date, assignee or links.",
        answers=CardDetail,
        changes=True,
        accepts=CardFields,
    ),
    Declaration(
        path="/projects/{project_id}/cards/{number}/move",
        method="POST",
        operation_id="move_card",
        summary="Move a card to a column, or to another place in its own; Blocked takes a reason. A card entering "
        "Done retires the known issues it fixes, or asks their authors to.",
        answers=MovedCard,
        changes=True,
        accepts=CardMove,
    ),
    Declaration(
        path="/projects/{project_id}/cards/{number}/claim",
        method="POST",
        operation_id="claim_card",
        summary="Claim an unassigned card in To do: the member becomes its assignee and it moves to Doing.",
        answers=CardDetail,
        changes=True,
    ),
    Declaration(
        path="/projects/{project_id}/cards/{number}/comment",
        method="POST",
        operation_id="comment_card",
        summary="Comment on a card; its assignee is told.",
        answers=CardDetail,
        changes=True,
        accepts=CardCommentText,
    ),
    Declaration(
        path="/projects/{project_id}/cards/{number}/delete",
        method="POST",
        operation_id="delete_card",
        summary="Delete a card, with its links and comments.",
        answers=DeletedCard,
        changes=True,
    ),
    Declaration(
        path="/audit",
        method="GET",
        operation_id="audit",
        summary="The company's audit log, newest first.",
        answers=AuditPage,
        query=("limit", "before", "member", "kind", "project", "since", "until"),
    ),
    Declaration(
        path="/export",
        # A POST with the console's header: a GET, which any page or image can make a signed-in browser send, would
        # start a whole export, and record one, for whoever opened it.
        method="POST",
        operation_id="export",
        summary="All of the company's data as one zip: the memory with its history, and the company's records. Admins only.",
        answers=None,
        changes=True,
        download="application/zip",
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
        summary="One folder of the company's memory: its folders, with what they hold, and its memories; deep, everything beneath it.",
        answers=Folder,
        query=("folder", "deep"),
    ),
    Declaration(
        path="/interviewed",
        method="GET",
        operation_id="interviewed",
        summary=(
            "The memories written from the signed-in member's interviews, which they author: each with the interview, "
            "who ran it and when. Changes nothing."
        ),
        answers=InterviewMemories,
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
        summary="Pin a project, department or company memory, or a topic folder, into every briefing it belongs in.",
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
        summary="Retire a memory that is no longer true; another author's raises a challenge instead.",
        answers=Retired,
        changes=True,
        accepts=MemoryPath,
    ),
    Declaration(
        path="/search",
        method="GET",
        operation_id="search_everywhere",
        summary="Memories that match, across company memory, department memory and every project this member can reach.",
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
        path="/notices",
        method="GET",
        operation_id="notices",
        summary="What this member has been told about their cards and challenges. Reading it here leaves each notice "
        "waiting for their next briefing.",
        answers=Notices,
    ),
    Declaration(
        path="/challenges/{challenge_id}/decide",
        method="POST",
        operation_id="decide_challenge",
        summary="Accept a challenge or reject it.",
        answers=DecidedChallenges,
        changes=True,
        accepts=Decision,
    ),
    Declaration(
        path="/rate-limits",
        method="GET",
        operation_id="rate_limits",
        summary="The server's rate limit, and whether the signed-in member may change it.",
        answers=RateLimits,
    ),
    Declaration(
        path="/rate-limits",
        method="POST",
        operation_id="change_rate_limits",
        summary="Change the server's rate limit, or switch it off.",
        answers=RateLimits,
        changes=True,
        accepts=RateLimitChange,
    ),
    Declaration(
        path="/license",
        method="GET",
        operation_id="license_state",
        summary="The server's license key: its status, company, member cap and expiry.",
        answers=LicenseState,
    ),
    Declaration(
        path="/license",
        method="POST",
        operation_id="install_license",
        summary="Install a license key on the server. Admins only.",
        answers=LicenseState,
        changes=True,
        accepts=LicenseKeyText,
    ),
    Declaration(
        path="/members",
        method="GET",
        operation_id="members",
        summary="Everyone in the company, with their role and GitHub account.",
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
        summary="Make another member the company's owner.",
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
        path="/my-time-zone",
        method="GET",
        operation_id="my_time_zone",
        summary="The signed-in member's time zone, and every time zone they can choose from.",
        answers=YourTimeZoneChoices,
    ),
    Declaration(
        path="/my-time-zone",
        method="POST",
        operation_id="choose_my_time_zone",
        summary="Choose the signed-in member's time zone, or none to have it detected from their browser.",
        answers=YourTimeZone,
        changes=True,
        accepts=ChosenTimeZone,
    ),
    Declaration(
        path="/my-time-zone/detected",
        method="POST",
        operation_id="report_my_time_zone",
        summary="Report the time zone the signed-in member's browser is set to, kept while they have chosen none.",
        answers=YourTimeZone,
        changes=True,
        accepts=DetectedTimeZone,
    ),
    Declaration(
        path="/members/{member_id}/token",
        method="POST",
        operation_id="reissue_token",
        summary="Issue a new personal token for a member of the company, revoking the one they had.",
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
        if declaration.download is not None:
            responses = {
                "200": {
                    "description": declaration.summary,
                    "content": {declaration.download: {"schema": {"type": "string", "format": "binary"}}},
                }
            }
        elif declaration.answers is None:
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
