# Shared Memory

A memory that every member's coding agent can read and write, so what one member's agent learns reaches every other member's agent and the team's ways of working stay consistent.

## Language

### Structure

**Team**:
The top-level group of members that owns projects and team memory.
_Avoid_: Company, organization, org

**Project**:
A named space within a team holding the memory for one product; one or more repositories point to it by its project ID.
_Avoid_: Workspace, namespace

**Repository**:
A git repository that belongs to a project, known by a short name unique within that project.
_Avoid_: Repo

### People and access

**Member**:
A person who belongs to a team and whose coding agent's sessions are connected to its memory.
_Avoid_: User, developer, dev, employee

**Owner**:
The one member of a team who can grant and revoke **admin** and hand ownership to another member; an owner can do everything an admin can.
_Avoid_: Super admin, root

**Admin**:
A member who manages the team's members, roles, projects and personal tokens, and can reach every project.
_Avoid_: Manager, superuser, moderator

**Project lead**:
A member who looks after one project: its access, its repositories and who else leads it.
_Avoid_: Maintainer, project admin, project owner

**Restricted project**:
A project only its **access list**, its project leads and the team's admins can reach; every other project is open to the whole team.
_Avoid_: Private project, locked project

**Access list**:
The members allowed into a restricted project.
_Avoid_: ACL, allowlist, permissions

**Personal token**:
The secret that proves which member a session belongs to; issued once per member.
_Avoid_: API key, password, project token

### Memory

**Memory**:
One Markdown file with a header of details; the unit that is saved, promoted, superseded, pinned and retired.
_Avoid_: Note, doc, context, knowledge

**Topic**:
A folder of memories with an index, used when a subject is too long for one memory.
_Avoid_: Long memory, folder memory

**Author**:
The member who wrote a memory.
_Avoid_: Owner, creator

**Level**:
Where a memory sits: local, personal, project or team.
_Avoid_: Tier, scope, L1/L2/L3

**Local memory**:
A coding agent's own built-in memory on one member's machine, such as Claude Code's; it never reaches the team.
_Avoid_: Private memory, auto memory

**Personal memory**:
A memory belonging to one member, readable by the whole team but not accepted by it.
_Avoid_: Draft, notes, my memory

**Project memory**:
A memory that holds for everyone working on one project.
_Avoid_: Shared memory

**Team memory**:
A memory that holds for every project in the team.
_Avoid_: Company memory, global memory, shared memory

**Area**:
The memory one save can change without waiting on others: the team memory, one project's project memory, or one member's personal memory in one project.
_Avoid_: Partition, shard, space, scope

**Exception**:
A project memory that deliberately overrides a named team memory for that one project.
_Avoid_: Override, local rule

**Outdated memory**:
A memory nobody has used for long enough that it may no longer be true.
_Avoid_: Stale, expired

### Memory types

**Convention**:
A rule for how the team works, followed every day.
_Avoid_: Standard, guideline

**Decision**:
A choice made once, recorded with its reasons and the alternatives rejected.
_Avoid_: ADR

**Architecture**:
How the system is built and how its parts relate.
_Avoid_: Design, overview

**Gotcha**:
A surprising fact that wastes time if you don't know it.
_Avoid_: Pitfall, trap, lesson

**Known issue**:
Something in a project that is broken now and expected to be fixed, with how to work around it; it lives in project memory and is retired once fixed.
_Avoid_: Bug, open issue, defect

### Changing memory

**Promote**:
To move a personal memory into project memory or team memory.
_Avoid_: Share, publish

**Contradiction**:
Two memories that cannot both be true.
_Avoid_: Conflict, collision

**Supersede**:
To put a new memory in an old one's place, keeping the old one in history.
_Avoid_: Replace, overwrite, update

**Challenge**:
A request to supersede or retire another author's memory, waiting for that author's decision.
_Avoid_: Approval, proposal, change request

**Reasoning**:
Why the member raising a challenge believes the memory it targets should be superseded or retired, carried on the challenge for whoever decides it.
_Avoid_: Argument, case, rationale, justification

**Retire**:
To mark a memory as no longer true without anything superseding it.
_Avoid_: Delete, archive

### Reading memory

**Briefing**:
What every session receives when it starts, or fetches with the briefing tool where its coding agent has no hook for it: the memories pinned for its project, the project's known issues, the member's own cards, and any notice waiting for the member, such as a challenge they must decide.
_Avoid_: Pinned set

**Pin**:
A mark that puts a memory into every briefing.
_Avoid_: Star, favorite

**Recall**:
Memories added to a prompt automatically because they match it.
_Avoid_: Injection, auto-search

**Hook**:
Where a coding agent calls the server by itself and takes the answer into the session: as the session starts, for the briefing, and as a prompt is submitted, for recall. Each family of agents needs that answer in its own shape; an agent with no hook uses the briefing tool and search instead.
_Avoid_: Callback, trigger, event handler

### The console

**Console**:
The web app where members browse memory and admins run the team; members sign in to it with GitHub.
_Avoid_: Dashboard, admin panel, web UI

**Audit log**:
The record of who changed members, roles, access, tokens, memory or cards, and when. It is not the memory's git history, which holds what memory said.
_Avoid_: History, activity, trail

### The board

**Board**:
A project's list of work its members track, laid out in four columns: To do, Doing, Blocked and Done.
_Avoid_: Kanban, tracker, backlog, todo list

**Card**:
One piece of work on a board, known by its number within the project.
_Avoid_: Ticket, task, todo, item, issue

**Assignee**:
The member working on a card.
_Avoid_: Owner, holder

**Claim**:
To make yourself a card's assignee by moving it from To do to Doing; only one member can claim a card.
_Avoid_: Grab, take, lock

**Blocked**:
The column for a card that cannot go on, with the reason it is waiting and, if it is another card, which one.
_Avoid_: Stuck, on hold

**Archive**:
The Done cards that have left a board, 14 days after they were done; they stay readable and can be reopened. It holds cards only: memory that is no longer true is retired, never archived.
_Avoid_: Trash, history, closed cards

### Sessions and collisions

**Coding agent**:
The AI coding tool a member's sessions run in: Claude Code, Codex, GitHub Copilot, Gemini CLI, Cursor, Devin Desktop or Cline. Called simply the *agent* where the meaning is plain; a session is never called an agent.
_Avoid_: Client, IDE, assistant, bot

**Session**:
One running conversation of a member's coding agent.
_Avoid_: Chat, conversation, agent

**Activity**:
A session's one-line statement of what it is working on.
_Avoid_: Status, working-on line

**Lock**:
A session's claim on a file in a repository that its coding agent is editing.

**Holder**:
The session holding a lock.
_Avoid_: Owner

**Takeover**:
Moving another session's lock to your own session.
_Avoid_: Steal, force-unlock

**Collision**:
Two sessions working on the same file or the same task at the same time.
_Avoid_: Conflict, clash
