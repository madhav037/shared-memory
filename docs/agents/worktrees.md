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

## Editing

Read a file with Read, in ranges for a large one such as `board.py`, and change it with Edit. Edit refuses a file
that was only read through the shell.
