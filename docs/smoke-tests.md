# Smoke tests with real Claude Code

The tests in `tests/` check the server through its HTTP interface. The smoke tests in `smoke/` check what those can't: that the plugin's wiring works in real Claude Code, and that Claude actually uses memory. They are slow and depend on the model, so they run nightly and by hand, never with `uv run pytest`.

Beside them, `smoke/stress.py` puts many members' coding agents on one server at once and reports latency, failures, recall and whether memory files, git and the search index agree: see [the stress test](stress-test.md). It runs only by hand.

## What they check

| Test | Checks |
|---|---|
| `test_the_hooks_and_the_mcp_connection_carry_the_members_identity` | The personal token, project ID and repository name reach both hooks and the MCP connection |
| `test_an_unreachable_server_does_not_block_the_prompt` | A server that is down shows "Shared Memory is unavailable" at session start, and the prompt still gets an answer |
| `test_a_slow_server_holds_up_the_prompt_for_only_a_few_seconds` | A server that doesn't answer costs the prompt at most a few seconds |
| `test_a_promoted_memory_reaches_a_teammates_next_prompt_without_a_search` | Success check 1 (`docs/design.md` §10.1) |
| `test_a_new_members_first_session_answers_which_package_manager_from_the_briefing` | Success check 2 |
| `test_the_prompt_hook_adds_under_one_second` | Success check 4, across three prompts in one session |

Each test starts its own server with a fresh database, then runs headless Claude Code (`claude --print`) with the plugin loaded from `plugin/` and configured for one **member** through `--settings`. Your own Claude Code settings, plugins and hooks aren't loaded.

## Run them by hand

Requirements: Postgres (`docker compose up -d db`), and Claude Code installed and signed in (or `ANTHROPIC_API_KEY` set).

```bash
uv run pytest smoke -v
```

A run takes about a minute and makes a few calls to Haiku. Set `SMOKE_CLAUDE_MODEL` (for example `sonnet`) to try another model.

## Nightly runs

`.github/workflows/smoke-tests.yml` runs them every night at 02:00 IST, and on demand from the repository's **Actions** tab (**Smoke tests**, then **Run workflow**).

- **Credentials:** add one repository secret, either `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (created with `claude setup-token`). Without one, each run is skipped with a warning.
- **Failures** open an issue labeled `smoke-test-failure`, or comment on the one already open. Close it once the tests pass again.
