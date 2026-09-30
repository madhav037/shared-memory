# The stress test

The stress test in `smoke/stress.py` puts a whole team's coding agents on one server at once: many **members**, each running several subagents, over MCP and the **hooks**. Rerun it before and after a change to the server and compare the reports. It is slow and its numbers depend on the machine, so it runs only by hand: never in CI, and never with `uv run pytest`.

## What a run does

1. Adds a fresh team with its own owner, members and project, so runs against one stack don't disturb each other.
2. Runs every member's subagents for the chosen time. Each subagent is a **session** of its own: one MCP connection and a session-start hook, then a mix of what a coding agent does with **memory**, with a pause between calls:

   | Share | Calls |
   |---|---|
   | 15% | the prompt hook, which brings **recall** |
   | 25% | `search` |
   | 10% | `tree` |
   | 5% | `list` of the member's own folder |
   | 7% | `read` of a memory it saved, or `briefing` before it has saved any |
   | 18% | `remember` |
   | 10% | `edit_memory` of a memory it saved |
   | 4% | `delete_memory` of a memory it saved |
   | 5% | `promote` to project memory, keeping both sides of any similar memories |
   | 1% | a resumed session's session-start hook |

3. With `--races`, races one member's subagents on the same memory: two edits of different fields, an edit against a delete, three promotes of one memory, and eight saves of one title.
4. Checks that the team's memory files, git and search index agree.

## The report

- **Per operation:** how many calls, and their p50, p95, p99 and maximum latency.
- **Failures:** transport errors, timeouts, server errors, and tool calls the server didn't expect to fail. **Refusals**, where the server said no and why, are listed apart.
- **Recall:** how many prompts the prompt hook added memories to.
- **Races:** how many trials broke each invariant; 0 is correct.
- **Consistency:** memory files on disk but missing from the search index, memories in the index but gone from disk, uncommitted changes in the memory folder, and whether `git fsck` passes.

The run exits 1 when there were failures, the consistency check disagrees, or a race broke an invariant. `--json report.json` also writes the whole report, to compare runs.

## Run it

Requirements: Docker, and `uv sync` done.

```bash
uv run python -m smoke.stress up                      # build and start the stress test's own stack
uv run python -m smoke.stress run --members 20 --subagents 3 --duration 60 --races
uv run python -m smoke.stress down                    # stop it and delete its data
```

`up` starts `smoke/stress-compose.yaml` under its own compose project (`shared-memory-stress`), with its own database and memory folder, and the server on `127.0.0.1:8100`. Pass `--compose-project` and `--port` to all three commands to run another copy beside it. `up --workers N` starts the server with `N` worker processes (`SHARED_MEMORY_WORKERS`, default 2); compare a run against `--workers 1` to see what several workers change. Each run has the server load its search model before the load starts; the first run after `up` also downloads it, which takes a minute or two.

| Option of `run` | Default | |
|---|---|---|
| `--members` | 20 | Members in the run's team |
| `--subagents` | 3 | Subagents per member, each its own session |
| `--duration` | 60 | Seconds of load |
| `--pace` | `0.05-0.4` | Seconds a subagent pauses between calls, drawn uniformly |
| `--races` | off | Race one member's subagents after the load |
| `--json` | | Also write the report to this file |

### Against a server of your own

The closing check reads the memory folder and the database directly. Against the stack it runs `smoke/stress_check.py` inside the server's container. For a server running on this machine, say where they are:

```bash
uv run python -m smoke.stress run --server-url http://127.0.0.1:8000 \
  --memory-root data/memory --database-url postgresql://postgres:postgres@127.0.0.1:5433/shared_memory
```

On Windows, keep the memory folder's path short: the server's paths inside it are long, and past Windows' 260-character limit saves fail.

## A reference run

20 members x 3 subagents for 60 s at the default pace, against the stack on one laptop (12 cores), at commit `bf14b56`:

| Operation | p50 | p95 | max |
|---|---|---|---|
| `remember` | 5.1 s | 7.6 s | 8.3 s |
| `edit_memory` | 5.6 s | 7.7 s | 8.5 s |
| `search` | 0.5 s | 1.1 s | 1.4 s |
| `tree` | 1.0 s | 2.0 s | 2.5 s |
| prompt hook | 1.3 s | 2.6 s | 3.0 s |

No failures; recall added memories to 52% of prompts; files, git and the search index agreed. A shorter run with `--races` lost a change in 6 of 20 concurrent edits, brought a deleted memory back in 3 of 20, and promoted one memory twice in 1 of 10 (spec #129).

The same load with 4 workers (`up --workers 4`), after spec #172, on the same laptop:

| Operation | p50 | p95 | max |
|---|---|---|---|
| `remember` | 0.68 s | 3.3 s | 7.2 s |
| `edit_memory` | 0.61 s | 3.5 s | 4.4 s |
| `search` | 0.11 s | 0.35 s | 2.3 s |
| `tree` | 0.58 s | 1.9 s | 2.9 s |
| prompt hook | 0.15 s | 0.43 s | 2.3 s |

78 calls/s, no failures, races 0, files, git and the search index agreed. At 200 agents (50 x 4) the server stays near 70 calls/s and everything waits longer (saves about 2 s at p50, the prompt hook about 3 s), still with no failures.
