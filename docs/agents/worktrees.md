# Working in a worktree

What a coding agent needs when it implements a ticket in its own worktree, next to others doing the same.

## Setting up

- Run `npm ci` in `console/` first: a new worktree has no `console/node_modules`.
- The tests need the Postgres from `docker compose up -d db`, run once from the main checkout. Each checkout names
  its own test databases, so worktrees share that one Postgres. `SHARED_MEMORY_TEST_ADMIN_URL` (`tests/support.py`)
  points the tests at another Postgres.
- The pre-commit hook in `.githooks/` runs `uv run ruff check`. `git config core.hooksPath .githooks`, run once in
  the main checkout, turns it on for that clone and every worktree made from it.

## Running tests

- Run the test files for the seam you touch. The full `uv run pytest` takes four minutes and enough memory that
  several at once get killed; when agents work in parallel, CI runs the full suite.
- Read pytest's own last line for the result. Piped through `tail`, the exit code is `tail`'s.

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
- **In tests**, the driver's `Session` has an `identifier`, `as_session(identifier)`, `end()` and `active_sessions()`.

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
  `remove` (one pattern, one at a time) is for the project's leads and the team's admins, and each writes a
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
    runs in (`$PWD`, or the current location in Cline's `.ps1`; `connection.working_folder_root`). Without git, or
    outside a repository, the header is empty. Codex's Windows command (cmd.exe) sends none. Their references don't
    say the command runs in the session's folder, so whether it does still waits for a hand-check in each agent.
  - Copilot CLI's hook posts by itself, with no command to ask git in, so it sends no root: a Copilot CLI session
    started in a subfolder still names its files from that subfolder. A known limit.

  `?format=` names the agent family, as on the other hooks, and `X-Shared-Memory-Agent` the coding agent.
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
- **Blocked** (`hooks.blocked`), only when another active session holds the file. The reason is who holds the file,
  followed by `TAKEOVER_IS_POSSIBLE` (`app.py`) in place of take_lock's own advice (`Held.told`):
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

## Editing

Read a file with Read, in ranges for a large one such as `board.py`, and change it with Edit. Edit refuses a file
that was only read through the shell.
