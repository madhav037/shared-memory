"""Headless Claude Code sessions with the Shared Memory plugin, as a member would run them."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.support import REPO_ROOT

PLUGIN_DIR = REPO_ROOT / "plugin"
PLUGIN_ID = "shared-memory@inline"
MEMORY_TOOLS = "mcp__plugin_shared-memory_shared-memory__"
MODEL = os.environ.get("SMOKE_CLAUDE_MODEL", "haiku")


def claude_executable() -> str | None:
    return shutil.which("claude")


@dataclass
class HookRun:
    event: str
    outcome: str
    output: str
    seconds: float


@dataclass
class ClaudeRun:
    """What one headless session did: its answers, the tools Claude called, and every hook that ran."""

    results: list[str] = field(default_factory=list)
    tool_uses: list[str] = field(default_factory=list)
    hooks: list[HookRun] = field(default_factory=list)

    @property
    def answer(self) -> str:
        return "\n".join(self.results)

    def hooks_for(self, event: str) -> list[HookRun]:
        return [hook for hook in self.hooks if hook.event == event]

    def memory_tools_used(self) -> list[str]:
        return [name.removeprefix(MEMORY_TOOLS) for name in self.tool_uses if name.startswith(MEMORY_TOOLS)]


def run_claude(
    workdir: Path,
    *,
    server_url: str,
    token: str,
    project: str,
    repository: str,
    prompts: list[str],
    timeout: float = 300,
) -> ClaudeRun:
    """Run one headless session in workdir with the plugin configured for this member, sending each prompt in turn."""
    executable = claude_executable()
    assert executable, "Claude Code is not installed: the claude command is not on PATH"
    settings = {
        "pluginConfigs": {PLUGIN_ID: {"options": {"server_url": server_url, "personal_token": token}}},
        "env": {"SHARED_MEMORY_PROJECT": project, "SHARED_MEMORY_REPOSITORY": repository},
    }
    command = [
        executable,
        "--print",
        "--model", MODEL,
        "--plugin-dir", str(PLUGIN_DIR),
        "--settings", json.dumps(settings),
        "--setting-sources", "project",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--include-hook-events",
        "--no-session-persistence",
        "--max-turns", "6",
    ]  # fmt: skip
    # A session started from inside another Claude Code session must not think it is nested.
    env = {key: value for key, value in os.environ.items() if key not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    process = subprocess.Popen(
        command,
        cwd=workdir,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    stdin, stdout, errors = process.stdin, process.stdout, process.stderr
    assert stdin and stdout and errors
    stderr: list[str] = []
    threading.Thread(target=lambda: stderr.extend(errors), daemon=True).start()
    killer = threading.Timer(timeout, process.kill)
    killer.start()
    run = ClaudeRun()
    started: dict[str, float] = {}
    waiting = list(prompts)

    def send_next() -> None:
        # One prompt at a time: prompts sent while Claude is busy are merged into a single turn.
        if waiting:
            message = {"type": "user", "message": {"role": "user", "content": waiting.pop(0)}}
            stdin.write(json.dumps(message) + "\n")
            stdin.flush()
        else:
            stdin.close()

    try:
        send_next()
        for line in stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            _record(run, event, started, time.monotonic())
            if event.get("type") == "result":
                send_next()
        process.wait()
    finally:
        killer.cancel()
    assert process.returncode == 0, f"claude exited with {process.returncode}: {''.join(stderr)[-2000:]}"
    return run


def _record(run: ClaudeRun, event: dict[str, Any], started: dict[str, float], now: float) -> None:
    kind, subtype = event.get("type"), event.get("subtype")
    if kind == "system" and subtype == "hook_started":
        started[event["hook_id"]] = now
    elif kind == "system" and subtype == "hook_response":
        began = started.pop(event["hook_id"], now)
        run.hooks.append(HookRun(event["hook_event"], event.get("outcome", ""), event.get("output", ""), now - began))
    elif kind == "assistant":
        for part in event["message"]["content"]:
            if part.get("type") == "tool_use":
                run.tool_uses.append(part["name"])
    elif kind == "result":
        run.results.append(event.get("result") or "")
