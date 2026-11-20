# Working in a worktree

What a coding agent needs when it implements a ticket in its own worktree, next to others doing the same.

## Setting up

- Branch from `origin/dev`, after `git fetch origin dev`, and check `git log -1` before starting: a worktree once
  started on an old release commit.
- Run `npm ci` in `console/` first: a new worktree has no `console/node_modules`.
- The tests need the Postgres from `docker compose up -d db`, run once from the main checkout. Each checkout names
  its own test databases, so worktrees share that one Postgres. `SHARED_MEMORY_TEST_ADMIN_URL` (`tests/support.py`)
  points the tests at another Postgres.
- The compose image gives pgvector 0.8 on Postgres 17; any other Postgres needs pgvector 0.8 or later. With an older
  one (Ubuntu's 0.6) the tests stop at once with "pgvector 0.8 or later is needed (found 0.6.0)".
- The tests need the search model in `.cache/fastembed`, which CI caches. Where it can't be downloaded, only CI's
  server job is authoritative for the recall, search and contradiction tests.
- The pre-commit hook in `.githooks/` runs `uv run ruff check`. `git config core.hooksPath .githooks`, run once in
  the main checkout, turns it on for that clone and every worktree made from it.

## Running tests

- Run the test files for the seam you touch. The full `uv run pytest` takes four minutes and enough memory that
  several at once get killed; when agents work in parallel, CI runs the full suite.
- Read pytest's own last line for the result. Piped through `tail`, the exit code is `tail`'s.

## Waiting for CI

Wait on a PR's `checks` job, or on its merge, with the Monitor tool: an until-loop on
`gh pr view <n> --json state` or `gh pr checks <n>`. When memory runs low the guard kills background shell loops
(twice in #373's run) and leaves a Monitor watch running.

## Finishing

Once your PR has merged, remove your worktree from the main checkout with `git worktree remove <path>`, and leave
its branch in place: a PR stacked on it still needs it.

## The console's API contract

A change to `console_contract.py` needs both generated files refreshed, from the repository root:

```
uv run shared-memory openapi > openapi.tmp && mv openapi.tmp console/openapi.json
cd console && npm run api:types
```

Writing to a temporary file first keeps a failed command from emptying `console/openapi.json`.

## Console tests

- `signed_in` and `signed_in_owner` in `tests/support.py` give a signed-in console client. A request that answers
  "Sign in to the console first." came from a client that isn't.
- Every test signs in with its own GitHub account number. When a second login uses a number another login in the
  module already used, `FakeGitHub` fails the test at once with "GitHub account number N is already 'one-login' in
  this fake GitHub, so 'other-login' cannot sign in with it." Give one of the two tests an unused number.

## Building on sessions

A ticket of #220 that keeps something per session (its activity, its locks) stands on `Sessions` in
`src/shared_memory/sessions.py`, built once in `build_app` as `sessions`. Its docstring lists the whole interface.
Only that module reads the `sessions` table; another module's rows refer to `Session.id`.

- **The calling session.** In a hook, `session_of(current, payload)` in `app.py`; in a tool that takes `session`,
  `sessions.touch(caller(ctx), session)`. Both move its last-seen time, which is what keeps it active.
- **A project's active sessions**: `sessions.active(project_id)`, a list of `Session`. A session's coding agent is
  what a tool call of its reported, or else what its hooks say (`hooks.agent_of`: the `X-Shared-Memory-Agent` header
  the plugin and every kit send, or the answer format where only one agent asks for it); `None` when neither has.
- **A session that ended or went idle.** Nothing sweeps, so count its rows as gone wherever you read them:
  `sessions.still_active(ids)` says which holders are active. `sessions.on_gone(listener)` calls you inside the
  transaction when a session ends or is found back from idle, to clear its rows.
- **A project's active sessions with their activity**: `activities.in_project(project_id)` in
  `src/shared_memory/activity.py`, built in `build_app` as `activities`. It gives a list of `SessionActivity`, oldest
  session first: `session` (the `Session`), `activity` (what it stated, else the title of its member's most recently
  claimed card in Doing, else `None`) and `from_card`. Reach is the asker's to check. `briefing_line(each)` is the
  line the briefing shows, and `ACTIVITY_LIMIT` the one place the length cap is named. That module owns the
  `session_activities` table and asks the board for the card through `Board.doing_titles`.
- **The idle time**: `sessions.idle_after`, from `Settings.session_idle_minutes`.
- **The session's UTC offset** (#592): `Session.utc_offset_minutes`, minutes east of UTC, which its session-start hook
  gives in `X-Shared-Memory-Utc-Offset` (`date +%z` in a POSIX shell, `Get-Date -Format zzz` in PowerShell, worked
  out in node by Gemini CLI's script) and the route keeps with `sessions.keep_utc_offset` (`hooks.utc_offset_named`
  reads it; a missing or malformed header leaves the kept one as it is). `reader_zone` in `app.py` falls back to it
  after the member's chosen and detected time zone. Copilot CLI's hooks post without a shell, so they send none.
- **Words waiting for a session** are gathered in one place, `waiting_for(current, session)` in `app.py`: the prompt
  hook asks it, and so do `take_lock`, `release_lock` and `set_activity`, whose answers carry them as `notices` for
  an agent with no prompt hook. Each is told once, wherever it is told. A module with something for a session adds it
  there, beside `sessions.waiting_notices(session)` (back from idle, or back after it had ended).
- **The briefing prompt starts no session.** Only the `briefing` tool called without `session` does; the prompt
  cannot be told the session, so it shows the briefing without the active sessions and without an identifier.
- **Collision warnings** are `Collisions` in `src/shared_memory/collisions.py`, built in `build_app` as `collisions`.
  It owns `activity_embeddings` (each session's activity as an embedding) and `collision_warnings` (what each session
  was warned about), and `collisions.warnings(caller, session)` is what `waiting_for` adds. `tests/test_collisions.py`
  runs its own server, whose embedder gives chosen activities chosen embeddings.
- **The gate** (ADR-0024) is `Gates` in `src/shared_memory/gates.py`, built in `build_app` as `gates`. It reads
  `Collisions.of(session)` and owns `gate_ends` (how each later and earlier pair's gate ended), `gate_answers`
  (each earlier member's agree or refuse, from `answer_gate`), `gate_starts` (the earlier session was told),
  `gate_urgents` (an urgent message from `send_message`, which gates the earlier session until answered) and
  `project_waits` (a project's own wait). The before-edit hook asks `gates.before_edit` before `locks.before_edit`; a gated edit takes
  no lock. `tests/test_gates.py` runs its own server with `test_collisions.py`'s chosen embeddings.
- **Mute** (#514) is `muted` on `sessions`, set by the `mute` tool through `Sessions.mute`. `waiting_for` passes
  `urgent_only` to `messages.waiting_notices` for a muted session on anything but the prompt hook, so a message that is
  not urgent waits for the next prompt or the unmute; gate notices and answers are untouched. `tests/test_mute.py`.
- **Standby** (ADR-0027) is `Standbys` in `src/shared_memory/standby.py`, built in `build_app` as `standbys` and kept
  on `app.state.standbys`. It owns `standbys`, one row per session's held standby. `await standbys.hold(session,
  news, awaits, seconds=None, gone=None)` holds one until it ends and gives an `Ended` (`ending`: news, nothing_yet,
  replaced, moved_on; `news`; `wait_left`; `at`; `message(zone)`; `member(zone)`, the warnings the news' `warning.Shown`
  notices carry (`warning.warnings_in`, rendered at `at`), or nothing_yet's hourglass warning): `news` is
  `functools.partial(waiting_for, caller, session)`,
  `seconds` a shorter hold for a held tool call, `gone` the request's `is_disconnected`. The prompt hook calls
  `standbys.end(session)`. `standbys.in_project(project_id)` gives each `Standby` held now (`session_id`, `awaits`:
  the member IDs whose answer it awaits) for the console. `POST /hooks/standby` is the background route; it draws
  on the tool hooks' rate limit, and doesn't count as a hook that reaches the session (#518), since an agent with no
  hooks runs it too. The `stand_by` tool is the held-call route: the same `hold` with `seconds`
  (`STAND_BY_SECONDS`, 45, unless asked; at most `Settings.standby_tool_cap_seconds`), answering as the endpoint does
  (`_standby_answer`). The cap and the check interval are `Settings.standby_cap_minutes` and
  `standby_check_seconds`. `tests/test_standby.py`.
- **Each agent's route to stand by** (#527) is in `connection.py`: `STAND_BY_IN_THE_BACKGROUND` (the background
  command first, the tool as fallback) and `STAND_BY_WITH_THE_TOOL` (each agent's seconds a call, and the tool timeout
  that allows them). `standby_habits` is the guidance AGENTS.md and Cursor's rule carry, with the background command
  for a POSIX shell and for PowerShell (`background_standby`, `background_standby_powershell`); `stands_by(agent)` is
  what each agent's connect output says. Claude Code's command is in the plugin's skill, whose "Standing by" names
  every route too.
- **In tests**, the driver's `Session` has an `identifier`, `as_session(identifier)`, `end()`, `active_sessions()`,
  `stand_by()` (a standby held on a thread of its own) and `on_standby()`.

### Locks

Locks are `Locks` in `src/shared_memory/locks.py`, built once in `build_app` as `locks` and kept on
`app.state.locks`. Only that module reads the `locks` table. Its docstring lists the whole interface.

- **Take and release**: `locks.take(session, path, repository=None)` gives a `Lock`, or a `NeverLocks` for a file
  that never locks; `locks.release(session, path, repository=None)` gives the `Lock` that ended. `session` is the
  `Session` that `sessions.touch` or `session_of` gave.
- **The refusals are typed**: `Held` carries `.lock`, the holder's details, and its message is what the tool shows;
  `NotHeld` (a release by a session that isn't the holder), `OutsideRepository` and `NoRepository`. A hook that must
  let an edit through catches the last two, and treats `NeverLocks` as allowed.
- **Who holds a file**: `locks.of(project_id, repository, path)`, a `Lock` or None. `Lock.holder` is the holder's
  `Session` (member, coding agent, identifier), with `taken_at`, `last_used_at` and `activity`.
- **A project's locks**: `locks.held(project_id)`, oldest first. Both reads leave out a lock whose holder is no
  longer active, and neither checks reach: that is the asker's.
- **A holder's activity** is `activities.of(holder)`, which `Locks` is built with: what the session stated, else its
  member's card in Doing, else None. It is one read per lock.
- **Never-lock patterns** are consulted in one place, `locks.never_locks(project_id, path)`, which gives the pattern
  matched or None: one of the built-in `NEVER_LOCK`, or else one of the project's own. A pattern without a slash is
  matched against the file's name at any depth, one with a slash against the whole path from the repository's root.
- **A project's own never-lock patterns** are `ProjectPatterns` in `locks.py`, built in `build_app` as
  `project_patterns` and kept on `app.state.project_patterns`. One list holds for all of a project's repositories.
  To read them: `project_patterns.of(project_id)`, a list of `NeverLockPattern` (`pattern`, `added_by` as a member
  ID, `added_at`), oldest first; it doesn't check reach, which is the asker's. The built-in list is the constant
  `NEVER_LOCK`, which always applies. Only `locks.py` reads the `never_lock_patterns` table.
- **The `never_lock` tool**: with nothing, any member of the project gets `built_in` and `project`; `add` or
  `remove` (one pattern, one at a time) is for the project's leads and the company's admins, and each writes a
  `never_lock_pattern_added` or `never_lock_pattern_removed` audit log entry whose target is the pattern. It takes
  no `session`, so it doesn't keep one active. Adding a pattern ends the locks held on files it matches, and each
  holder is told once, through `locks.waiting_notices`.
- **A path** reaches `take` as the agent wrote it and is kept by `from_root(path)`: relative to the repository's
  root, with forward slashes. An absolute path is refused as outside the repository, so a hook that is handed one
  makes it relative first.
- **A takeover** is `locks.take(session, path, repository, takeover=True)`, which the `take_lock` tool reaches with
  `takeover: true`: another active session's lock moves to the caller with no consent from its holder. On a free
  file, or one the caller holds, it is an ordinary take and nobody is told.
- **When an agent offers a takeover**: only after `take_lock` (or the before-edit hook) refused it with `Held`. It
  tells its member who holds the file and offers the takeover; it passes `takeover: true` only once the member has
  said so, never on its own. `Held`'s message and `take_lock`'s description both say this, and every agent's
  guidance says the same.
- **The old holder is told once**: `locks.waiting_notices(session)` gives the takeovers of locks that session held
  and marks them told. `waiting_for` asks it, for the prompt hook and for the tools that answer with `notices`. The
  tools ask after their own work succeeded: a refusal carries none, so they stay waiting. An agent told of a takeover stops editing that file and tells its
  member.

### The before-edit hook

`POST /hooks/before-edit` checks or takes the lock on the file an edit tool is about to change. Claude Code's plugin
runs it on `PreToolUse` for `Edit|Write|MultiEdit|NotebookEdit`; another agent's kit posts to the same endpoint.

- **Headers**: `Authorization`, `X-Shared-Memory-Project` and `X-Shared-Memory-Repository`, as every hook sends, and
  `X-Shared-Memory-Root`, the absolute path of the repository's root, so a session started in a subfolder names its
  files as one started at the root does:
  - Where the agent gives its hook a folder (Claude Code's `$CLAUDE_PROJECT_DIR`, Devin's, Gemini CLI's): that
    folder followed by the way up to the root that `git rev-parse --show-cdup` gives (`connection.repository_root`).
    Without git the folder stands alone.
  - Codex, Cursor and Cline give their hooks no folder, so their kits ask git from the folder the hook's command
    runs in (`$PWD`, or the current location in PowerShell: Cline's `.ps1` and Codex's Windows command;
    `connection.working_folder_root`). Without git, or outside a repository, the header is empty. Codex was seen to
    run the command in the session's folder (#275); the others' references don't say, so that still waits for a
    hand-check in each agent.
  - Copilot CLI's hook posts by itself, with no command to ask git in, so it sends no root: a Copilot CLI session
    started in a subfolder still names its files from that subfolder. A known limit.

  `?format=` names the agent family, as on the other hooks, and `X-Shared-Memory-Agent` the coding agent. Each
  agent's header value and before-edit format are one `AgentHooks` record in `hooks.AGENTS`, which the kits in
  `connection.py` send from; each format's two answer shapes are one `Family` in `hooks.py`.
- **Payload**: the agent's own before-a-tool payload. Read from it: the session (`hooks.session_in`), the files
  (`hooks.edited_files`), and the working folder, `cwd`, or the open folders (`workspace_roots`, `workspaceRoots`),
  which stand in for the root when the header is missing, and also when the header's root doesn't hold the edited
  file: a root named from the wrong folder never turns a lockable edit into one outside the repository. The file is
  in `tool_input.file_path`,
  `tool_input.notebook_path` or `tool_input.path`; in the patch of Codex's `apply_patch` (`tool_input.command`, which
  may name several files: the first one held blocks the edit, and `locks.take_all` gives back the locks it took for
  it); in Copilot CLI's `toolArgs.path`; or in Cline's
  `preToolUse.parameters.path`. Copilot CLI and Cline give tools that only read a file a `path` too, so for those two
  the tool's name must be one that changes a file. An agent that names its file or its root in another field is
  added in `hooks.edited_files`.
- **The file's path from the root** is the file's absolute path with the root cut off the front; a file not under
  the root is outside the repository. A relative path (Codex's patch, Cline's tools) is read from the payload's
  working folder, its `cwd` or else its first open folder, so it too is cut from a root above that folder; with no
  such folder it is taken as written from the root.
- **Allowed** is answered `{}` in every family: a free file (now locked for the session), the session's own lock, a
  never-lock file, a path outside the repository, an unreadable payload, a payload naming no session or no file, an
  unknown personal token, a server error. Never an explicit "allow", which would skip the agent's own permission
  prompt.
- **The decision** is `locks.before_edit(session, files)`, beside `Locks`: it takes or keeps each file's lock and
  gives the reason the edit is blocked, or None to let it through. `app.py` only wires the hook to it.
- **Tied memories** (#549) are the hook's optional part, as recall is the prompt hook's: `recall.for_edit(caller,
  files, session)` gives the memories within the caller's reach tied to the edited files (`tied.tied_to`), in recall's
  framing and fence, through `hooks.answered`, and only where `hooks.hears_before_tool` (Claude Code, Codex, Cline).
  It runs within the recall budget or is dropped, only for an edit that went ahead: a gated or locked edit is told
  only why, and its memories stay untold. What it tells goes in `recall_told` with recall's, every section of each
  memory, so neither hook repeats the other, and a compaction's `recall.forget` starts both over. A tied memory
  counts as told while some section of it was told and none told has changed since.
- **Blocked** (`hooks.blocked`), only when another active session holds the file. The reason is who holds the file,
  followed by `TAKEOVER_IS_POSSIBLE` (`locks.py`) in place of take_lock's own advice (`Held.told`):
  - `claude`: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": reason}}`, which Codex reads too
  - `gemini`: `{"decision": "deny", "reason": reason}`
  - `devin`: `{"decision": "block", "reason": reason}`
  - `copilot-cli`: `{"permissionDecision": "deny", "permissionDecisionReason": reason}`
  - `cursor`: `{"permission": "deny", "user_message": reason, "agent_message": reason}`
  - `cline`: `{"cancel": true, "errorMessage": reason}`

  Only Claude Code's shape has been run in the real agent; the others are written from each agent's hook
  reference and wait for a hand-check in that agent (#229's pull request lists them).
- **The hook's own command** limits curl to 3 seconds and, when curl fails, prints a `systemMessage` warning instead,
  so the edit goes ahead. The server always answers 200.
- **Every other agent's kit** (`connection.py`) wires the same endpoint where the agent can refuse an edit: Codex,
  Copilot CLI, Gemini CLI, Cursor (not on Windows), Devin Desktop and Cline, each giving up at 3 seconds and letting
  the edit through, and each with a session-end hook beside it. `BEFORE_EDIT_HOOK` and `GUIDANCE_ONLY` name who has
  the hook and who is asked by the guidance to call `take_lock` instead; `SESSION_HABITS` is the guidance, and the
  skill and the server's instructions say the same.
- **In tests**, the driver's `Session.edit(path)` fires the hook as Claude Code's Edit tool does, and
  `tests/test_before_edit.py` has each other agent's own payload (`AGENTS_OWN`) and runs each kit's command.

## Last use and possibly outdated memory

`Uses` in `src/shared_memory/uses.py`, built in `build_app` as `uses`, owns `memory_uses`: each memory's last use.
Its docstring lists the interface. Only recall and the `read` tool call `uses.used`; the console never does. Whether a
memory is pinned comes from `briefing.pinned_among`. In tests, move the server's `TestClock` past
`outdated_after_days`; `tests/test_outdated_memory.py` is the prior art.

## Project health

`ProjectHealth` in `src/shared_memory/health.py`, built in `build_app` beside `ConsoleApi`, is a read model with no
table: `of(caller)` asks `Identity.looks_after`, `Uses` and `Challenges` about the project memory under
`projects/<id>/shared` and gives a typed `Health`. `GET /api/projects/{project_id}/health` serves it; the console's
page is `HealthPage.tsx`, linked from project settings when `you_may_change`. A later section of spec #504 adds a list
to `Health` and to the `ProjectHealth` model. `tests/test_project_health.py` and `console/e2e/project-health.spec.ts`.

## Editing

Read a file with Read, in ranges for a large one such as `board.py`, and change it with Edit. Edit refuses a file
that was only read through the shell.
