"""The stress test: many members, each running several subagents, on one server at once (docs/stress-test.md).

    uv run python -m smoke.stress up                   # start the stress test's own stack
    uv run python -m smoke.stress run --members 20 --subagents 3 --duration 60 [--races]
    uv run python -m smoke.stress down                 # stop it and delete its data

Each run adds a fresh team with its own members and project, so runs against one stack don't disturb each other.
Every subagent is a session of its own: one MCP connection, a session-start hook, then a mix of reads, saves and
prompt hooks with a pause between calls. Afterwards the run reports latency per operation, failures, recall's hit
rate, and whether the team's memory files, git and search index still agree.

Never part of CI or `uv run pytest`: it's for comparing the server under load before and after a change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import httpx
import httpx2
from mcp import Client, types
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent
COMPOSE_FILE = HERE / "stress-compose.yaml"
CHECK_SCRIPT = HERE / "stress_check.py"
DEFAULT_COMPOSE_PROJECT = "shared-memory-stress"
DEFAULT_PORT = 8100
REPOSITORY = "app"

T = TypeVar("T")

# What members save: realistic memories, so recall and the promote similarity check have something to match.
TOPICS = [
    ("Use pnpm for installs", "pnpm is our package manager", "convention",
     "Install with pnpm install; npm writes a second lockfile."),
    ("Postgres migrations run in CI", "migrations are applied by CI", "decision",
     "We apply schema migrations from CI, never by hand."),
    ("Billing talks to Stripe via a queue", "billing is async", "architecture",
     "The billing service enqueues Stripe calls on SQS."),
    ("Timezones in the scheduler", "the scheduler stores UTC", "gotcha",
     "The scheduler stores UTC and converts at the edge only."),
    ("Feature flags live in LaunchDarkly", "flags are in LaunchDarkly", "decision",
     "Every flag is created in LaunchDarkly with an owner."),
    ("Retry HTTP calls with backoff", "retries use exponential backoff", "convention",
     "Wrap outbound HTTP in retry with jittered backoff."),
    ("The cache is Redis with 5 minute TTL", "cache TTL is 5 minutes", "architecture",
     "Reads go through Redis; entries expire after 5 minutes."),
    ("Do not log card numbers", "never log PANs", "gotcha",
     "The logger redacts PANs but only on the payment path."),
]
# What members ask: prompts for the prompt hook and queries for search.
PROMPTS = [
    "how do we install packages", "database migrations", "stripe billing", "timezone bugs", "feature flags",
    "retry policy", "redis cache ttl", "logging sensitive data", "how is the scheduler built", "CI pipeline",
]


# --- reaching the server -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stack:
    """The server under test, and how to run a command beside it: to create a team, and to read its memory folder
    and database for the closing check."""

    url: str
    compose_project: str | None = None  # None: the server runs on this machine
    memory_root: str = "/data/memory"
    database_url: str | None = None

    def _beside_server(self, command: Sequence[str]) -> list[str]:
        if self.compose_project is None:
            return list(command)
        return [*compose(self.compose_project), "exec", "-T", "server", *command]

    def _env(self) -> dict[str, str] | None:
        if self.compose_project is not None:
            return None
        assert self.database_url is not None
        return dict(os.environ, SHARED_MEMORY_DATABASE_URL=self.database_url, SHARED_MEMORY_ROOT=self.memory_root)

    def setup_team(self, team: str) -> str:
        """Create a team with an owner; return the owner's personal token."""
        cli = ["shared-memory"] if self.compose_project else [sys.executable, "-c", "from shared_memory.cli import main; main()"]
        done = subprocess.run(
            self._beside_server([*cli, "setup", "--team", team, "--owner-member-id", "owner", "--owner-name", "Owner"]),
            capture_output=True, text=True, env=self._env(), check=False,
        )
        for line in done.stdout.splitlines():
            if line.startswith("Owner personal token:"):
                return line.split(":", 1)[1].strip()
        raise SystemExit(f"Couldn't create team {team}:\n{done.stdout}{done.stderr}")

    def check(self, team: str) -> dict[str, Any]:
        """Whether the team's memory files, git and search index agree (stress_check.py)."""
        python = "python" if self.compose_project else sys.executable
        done = subprocess.run(
            self._beside_server([python, "-", self.memory_root, team]),
            input=CHECK_SCRIPT.read_text(), capture_output=True, text=True, env=self._env(), check=False,
        )
        if done.returncode != 0:
            raise SystemExit(f"The consistency check failed to run:\n{done.stderr}")
        result: dict[str, Any] = json.loads(done.stdout)
        return result


def compose(project: str) -> list[str]:
    return ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE)]


def wait_until_answering(url: str, seconds: float = 300) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            httpx.post(f"{url}/hooks/session-start", json={}, timeout=5)
            return
        except httpx.HTTPError:
            time.sleep(1)
    raise SystemExit(f"The server at {url} didn't answer within {seconds:.0f}s.")


# --- a session -----------------------------------------------------------------------------------------------------


class Refusal(Exception):
    """A tool call came back as an error result: the server said no."""


class Session:
    """One subagent's session: the MCP connection it keeps for its whole life, and its hooks."""

    def __init__(self, url: str, token: str, project: str | None) -> None:
        self.url = url
        self.headers = {"Authorization": f"Bearer {token}", "X-Shared-Memory-Repository": REPOSITORY}
        if project:
            self.headers["X-Shared-Memory-Project"] = project
        self.session_id = str(uuid.uuid4())
        self._stack = AsyncExitStack()
        self._client: Client | None = None

    async def __aenter__(self) -> Session:
        http = await self._stack.enter_async_context(httpx2.AsyncClient(headers=self.headers, timeout=120))
        transport = streamable_http_client(f"{self.url}/mcp", http_client=http)
        self._client = await self._stack.enter_async_context(
            Client(transport, client_info=types.Implementation(name="claude-code", version="1.0"))
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    async def call(self, tool: str, **arguments: Any) -> Any:
        assert self._client is not None
        result = await self._client.call_tool(tool, arguments)
        text = "\n".join(getattr(part, "text", "") for part in result.content)
        if result.is_error:
            # The server's refusals say why; an error it didn't expect comes back as this text and nothing more.
            if text.strip() == f"Error executing tool {tool}":
                raise RuntimeError(text)
            raise Refusal(text)
        structured = result.structured_content
        if structured is not None:
            return structured["result"] if set(structured) == {"result"} else structured
        return text

    async def hook(self, http: httpx.AsyncClient, event: str, **payload: Any) -> dict[str, Any]:
        claude_event = {"session-start": "SessionStart", "prompt-submitted": "UserPromptSubmit"}[event]
        body = {"session_id": self.session_id, "cwd": f"/work/{REPOSITORY}", "hook_event_name": claude_event, **payload}
        response = await http.post(f"{self.url}/hooks/{event}", json=body, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        answer: dict[str, Any] = response.json()
        return answer


# --- the load ------------------------------------------------------------------------------------------------------


@dataclass
class Results:
    latency: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    failures: Counter[str] = field(default_factory=Counter)  # transport errors, timeouts, server errors
    refusals: Counter[str] = field(default_factory=Counter)  # the server said no
    prompts: int = 0
    prompts_with_recall: int = 0

    async def timed(self, operation: str, call: Awaitable[T]) -> T:
        start = time.perf_counter()
        try:
            return await call
        except Refusal as refused:
            self.refusals[f"{operation}: {str(refused)[:100]}"] += 1
            raise
        except Exception as error:
            self.failures[f"{operation}: {type(error).__name__} {str(error)[:120]}"] += 1
            raise
        finally:
            self.latency[operation].append(time.perf_counter() - start)


async def subagent(
    url: str, member_id: str, token: str, project: str, results: Results, until: float, pace: tuple[float, float],
    http: httpx.AsyncClient,
) -> None:
    """One subagent working until the deadline: a realistic mix of what a coding agent does with memory."""
    rng = random.Random()
    mine: list[str] = []  # this subagent's personal memories, still personal
    try:
        async with Session(url, token, project) as session:
            await results.timed("hook: session start", session.hook(http, "session-start", source="startup"))
            while time.monotonic() < until:
                roll = rng.random()
                try:
                    if roll < 0.15:
                        results.prompts += 1
                        answer = await results.timed(
                            "hook: prompt submitted", session.hook(http, "prompt-submitted", prompt=rng.choice(PROMPTS))
                        )
                        if (answer.get("hookSpecificOutput") or {}).get("additionalContext"):
                            results.prompts_with_recall += 1
                    elif roll < 0.40:
                        await results.timed("search", session.call("search", query=rng.choice(PROMPTS)))
                    elif roll < 0.50:
                        await results.timed("tree", session.call("tree"))
                    elif roll < 0.55:
                        folder = f"projects/{project}/people/{member_id}"
                        await results.timed("list", session.call("list", folder=folder))
                    elif roll < 0.62 and mine:
                        await results.timed("read", session.call("read", path=rng.choice(mine)))
                    elif roll < 0.62:
                        await results.timed("briefing", session.call("briefing"))
                    elif roll < 0.80:
                        title, summary, kind, body = rng.choice(TOPICS)
                        tag = uuid.uuid4().hex[:6]
                        saved = await results.timed("remember", session.call(
                            "remember", title=f"{title} {tag}", summary=summary, type=kind,
                            body=f"{body}\n\nNoted by {member_id} ({tag}).", topic=rng.choice([None, None, "backend"]),
                        ))
                        mine.append(saved["path"])
                    elif roll < 0.90 and mine:
                        await results.timed("edit_memory", session.call(
                            "edit_memory", path=rng.choice(mine), body=f"Edited at {time.time()} by {member_id}."
                        ))
                    elif roll < 0.94 and mine:
                        path = mine.pop(rng.randrange(len(mine)))
                        await results.timed("delete_memory", session.call("delete_memory", path=path))
                    elif roll < 0.99 and mine:
                        path = mine.pop(rng.randrange(len(mine)))
                        first = await results.timed("promote", session.call("promote", path=path, level="project"))
                        if first["status"] == "similar_memories":
                            await results.timed("promote (resolved)", session.call(
                                "promote", path=path, level="project", reference=first["reference"],
                                resolutions={similar["path"]: "keep_both" for similar in first["similar"]},
                            ))
                    else:
                        await results.timed("hook: session start", session.hook(http, "session-start", source="resume"))
                except Refusal:
                    pass
                except Exception:
                    await asyncio.sleep(0.2)
                await asyncio.sleep(rng.uniform(*pace))  # the coding agent thinks between calls
    except Exception as error:
        results.failures[f"connect: {type(error).__name__} {str(error)[:120]}"] += 1


# --- races ---------------------------------------------------------------------------------------------------------


async def races(url: str, token: str, project: str) -> dict[str, str]:
    """One member's parallel subagents hitting the same memory at the same instant. Each line counts the trials that
    broke an invariant; 0 everywhere is correct."""
    sessions = [Session(url, token, project) for _ in range(8)]
    found: dict[str, str] = {}
    async with AsyncExitStack() as stack:
        for session in sessions:
            await stack.enter_async_context(session)
        first = sessions[0]

        async def remember(title: str, body: str = "original body") -> str:
            saved = await first.call("remember", title=f"{title} {uuid.uuid4().hex[:8]}", summary="original summary",
                                     type="convention", body=body)
            path: str = saved["path"]
            return path

        lost = 0
        for trial in range(20):
            path = await remember("Race edit")
            await asyncio.gather(
                sessions[1].call("edit_memory", path=path, summary=f"new summary {trial}"),
                sessions[2].call("edit_memory", path=path, body=f"new body {trial}"),
                return_exceptions=True,
            )
            now = await first.call("read", path=path)
            if now["summary"] != f"new summary {trial}" or now["body"].strip() != f"new body {trial}":
                lost += 1
        found["two edits of different fields: a change was lost"] = f"{lost}/20"

        back = 0
        for _ in range(20):
            path = await remember("Race delete")
            await asyncio.gather(
                sessions[3].call("delete_memory", path=path),
                sessions[4].call("edit_memory", path=path, body="edited"),
                return_exceptions=True,
            )
            try:
                await first.call("read", path=path)
                back += 1
            except Refusal:
                pass
        found["an edit racing a delete: the memory came back"] = f"{back}/20"

        twice = 0
        for _ in range(10):
            path = await remember("Race promote", body=f"zqx {uuid.uuid4().hex} unrelated words")
            outcomes = await asyncio.gather(
                *(session.call("promote", path=path, level="project") for session in sessions[5:8]),
                return_exceptions=True,
            )
            if sum(isinstance(o, dict) and o.get("status") == "promoted" for o in outcomes) > 1:
                twice += 1
        found["three promotes of one memory: promoted more than once"] = f"{twice}/10"

        title = f"Same title {uuid.uuid4().hex[:6]}"
        saved = await asyncio.gather(*(
            session.call("remember", title=title, summary="s", type="decision", body=f"body {n}")
            for n, session in enumerate(sessions)
        ))
        overwritten = 8 - len({memory["path"] for memory in saved})
        found["eight saves of one title: memories overwritten"] = f"{overwritten}/8"
    return found


# --- a run ---------------------------------------------------------------------------------------------------------


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


async def run(stack: Stack, members: int, subagents: int, duration: float, pace: tuple[float, float],
              with_races: bool) -> dict[str, Any]:
    team = f"stress-{uuid.uuid4().hex[:6]}"
    owner_token = stack.setup_team(team)
    async with Session(stack.url, owner_token, None) as owner:
        project = (await owner.call("create_project", name=f"Stress {team}", repository=REPOSITORY))["project_id"]
        tokens: dict[str, str] = {}
        for n in range(1, members + 1):
            member_id = f"m{n:02d}"
            added = await owner.call("add_member", member_id=member_id, name=f"Member {n}")
            tokens[member_id] = added["personal_token"]
    async with Session(stack.url, owner_token, project) as owner:
        # The server loads the search model on its first search; that shouldn't count against the first saves.
        await owner.call("search", query="warm up")
    print(f"Team {team}: {members} members x {subagents} subagents = {members * subagents} sessions "
          f"for {duration:.0f}s against {stack.url}", flush=True)

    results = Results()
    until = time.monotonic() + duration
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=1000)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=120, limits=limits) as http:
        await asyncio.gather(*(
            subagent(stack.url, member_id, token, project, results, until, pace, http)
            for member_id, token in tokens.items() for _ in range(subagents)
        ))
    wall = time.perf_counter() - started

    race_results = None
    if with_races:
        print("Racing ...", flush=True)
        race_results = await races(stack.url, next(iter(tokens.values())), project)

    return {
        "team": team,
        "members": members,
        "subagents_per_member": subagents,
        "duration_seconds": duration,
        "pace_seconds": list(pace),
        "wall_seconds": round(wall, 1),
        "operations": {
            operation: {
                "count": len(values),
                "p50": percentile(values, 0.50),
                "p95": percentile(values, 0.95),
                "p99": percentile(values, 0.99),
                "max": max(values),
            }
            for operation, values in sorted(results.latency.items())
        },
        "failures": dict(results.failures.most_common()),
        "refusals": dict(results.refusals.most_common()),
        "recall": {"prompts": results.prompts, "with_recalled_memories": results.prompts_with_recall},
        "races": race_results,
        "consistency": stack.check(team),
    }


def consistent(report: dict[str, Any]) -> bool:
    check = report["consistency"]
    return not (check["not_searchable"] or check["searchable_but_gone"] or check["uncommitted"]) and check["git_fsck_ok"]


def race_problems(report: dict[str, Any]) -> int:
    return sum(int(outcome.split("/")[0]) for outcome in (report["races"] or {}).values())


def print_report(report: dict[str, Any]) -> None:
    calls = sum(op["count"] for op in report["operations"].values())
    print(f"\n{calls} calls in {report['wall_seconds']:.0f}s ({calls / report['wall_seconds']:.1f}/s), "
          f"{sum(report['failures'].values())} failures, {sum(report['refusals'].values())} refusals\n")
    print(f"{'operation':24}{'count':>7}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}")
    for name, op in report["operations"].items():
        print(f"{name:24}{op['count']:>7}" + "".join(f"{op[p]:>8.2f}s" for p in ("p50", "p95", "p99", "max")))

    recall = report["recall"]
    if recall["prompts"]:
        rate = recall["with_recalled_memories"] / recall["prompts"]
        print(f"\nRecall: {recall['with_recalled_memories']} of {recall['prompts']} prompts got memories ({rate:.0%})")
    for label in ("failures", "refusals"):
        if report[label]:
            print(f"\n{label.capitalize()}:")
            for what, count in list(report[label].items())[:12]:
                print(f"  {count:>5}  {what}")
    if report["races"] is not None:
        print("\nRaces (0 is correct):")
        for what, outcome in report["races"].items():
            print(f"  {outcome:>6}  {what}")

    check = report["consistency"]
    print(f"\nFiles, git and the search index {'agree' if consistent(report) else 'DISAGREE'}: "
          f"{check['memory_files']} memory files, {check['indexed_memories']} searchable, {check['commits']} commits")
    for label, key in (("on disk but not searchable", "not_searchable"),
                       ("searchable but gone from disk", "searchable_but_gone"), ("uncommitted", "uncommitted")):
        if check[key]:
            print(f"  {len(check[key])} {label}: {check[key][:3]}")
    if not check["git_fsck_ok"]:
        print(f"  git fsck: {check['git_fsck_output']}")


# --- the command line ----------------------------------------------------------------------------------------------


def pace_range(text: str) -> tuple[float, float]:
    low, _, high = text.partition("-")
    return float(low), float(high or low)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m smoke.stress", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help in (("up", "Build and start the stress test's own stack."),
                       ("down", "Stop the stress test's stack and delete its data."),
                       ("run", "Run the load against a server, then check it.")):
        command = commands.add_parser(name, help=help)
        command.add_argument("--compose-project", default=DEFAULT_COMPOSE_PROJECT,
                             help=f"The stack's compose project name (default {DEFAULT_COMPOSE_PROJECT}).")
        command.add_argument("--port", type=int, default=DEFAULT_PORT,
                             help=f"The port the stack's server listens on, on 127.0.0.1 (default {DEFAULT_PORT}).")
    run_command = commands.choices["run"]
    run_command.add_argument("--members", type=int, default=20)
    run_command.add_argument("--subagents", type=int, default=3, help="Subagents per member, each its own session.")
    run_command.add_argument("--duration", type=float, default=60, help="Seconds of load.")
    run_command.add_argument("--pace", type=pace_range, default=(0.05, 0.4), metavar="LOW-HIGH",
                             help="Seconds a subagent pauses between calls, drawn uniformly (default 0.05-0.4).")
    run_command.add_argument("--races", action="store_true",
                             help="After the load, race one member's subagents on the same memory.")
    run_command.add_argument("--server-url", help="A server this machine runs instead of the stack; needs "
                             "--memory-root and --database-url for creating the team and the closing check.")
    run_command.add_argument("--memory-root", help="That server's memory folder (SHARED_MEMORY_ROOT).")
    run_command.add_argument("--database-url", help="That server's database (SHARED_MEMORY_DATABASE_URL).")
    run_command.add_argument("--json", type=Path, help="Also write the report here, to compare runs.")
    args = parser.parse_args(argv)

    if args.command == "up":
        subprocess.run([*compose(args.compose_project), "up", "-d", "--build", "--wait"], check=True,
                       env={**os.environ, "STRESS_PORT": str(args.port)})
        wait_until_answering(f"http://127.0.0.1:{args.port}")
        print(f"The stress test's stack answers at http://127.0.0.1:{args.port}.")
        return 0
    if args.command == "down":
        subprocess.run([*compose(args.compose_project), "down", "-v"], check=True)
        return 0

    if args.server_url:
        if not (args.memory_root and args.database_url):
            parser.error("--server-url needs --memory-root and --database-url")
        stack = Stack(args.server_url.rstrip("/"), None, args.memory_root, args.database_url)
    else:
        stack = Stack(f"http://127.0.0.1:{args.port}", args.compose_project)
    wait_until_answering(stack.url, seconds=10)
    report = asyncio.run(run(stack, args.members, args.subagents, args.duration, args.pace, args.races))
    print_report(report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
    healthy = not report["failures"] and consistent(report) and race_problems(report) == 0
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
