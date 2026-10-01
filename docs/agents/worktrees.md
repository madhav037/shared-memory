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
  `None` until one of its tool calls has reported it, because a hook does not say.
- **A session that ended or went idle.** Nothing sweeps, so count its rows as gone wherever you read them:
  `sessions.still_active(ids)` says which holders are active. `sessions.on_gone(listener)` calls you inside the
  transaction when a session ends or is found back from idle, to clear its rows.
- **The idle time**: `sessions.idle_after`, from `Settings.session_idle_minutes`.
- **Words for the session's next prompt** go in the prompt hook's `notices` in `app.py`, beside
  `sessions.waiting_notices(session)`.
- **In tests**, the driver's `Session` has an `identifier`, `as_session(identifier)`, `end()` and `active_sessions()`.

## Editing

Read a file with Read, in ranges for a large one such as `board.py`, and change it with Edit. Edit refuses a file
that was only read through the shell.
