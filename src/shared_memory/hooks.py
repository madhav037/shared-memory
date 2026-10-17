"""The adapter between the hook endpoints and each coding agent family's own hook format (ADR-0011).

Every agent's hooks post to the same endpoints and name, as ?format=, the family whose shape they can read:

- `claude`: `hookSpecificOutput`, for Claude Code, Codex, Gemini CLI, Devin Desktop and Copilot in VS Code;
- `gemini` and `devin`: the same shape for context, and their own when an edit is blocked;
- `copilot-cli`: `additionalContext` at the top level;
- `cursor`: `additional_context`, which only Cursor's session start can take in;
- `cline`: `contextModification`, beside the `cancel` that keeps the task going.

A format this server doesn't know, or none at all, is answered in Claude Code's shape, which is what these endpoints
have always answered. Nothing here ever refuses or raises: a hook that cannot be answered is answered emptily, so no
session is ever held up by the state of the team's memory.

The before-edit hook is the one that can stop its agent, and for one reason only: another active session holds the
file's lock. `blocked` shapes that answer for each family:

- `claude`: `permissionDecision: "deny"` and its reason inside `hookSpecificOutput`, which Codex reads too;
- `gemini`: `decision: "deny"` with a `reason`;
- `devin`: `decision: "block"` with a `reason`;
- `copilot-cli`: `permissionDecision` and its reason at the top level;
- `cursor`: `permission: "deny"`, with the reason once for its agent and once for its member;
- `cline`: `cancel: true` with an `errorMessage`.

An allowed edit is answered emptily in every family, which leaves the agent's own permission rules to decide as if
the hook weren't there. `edited_files` reads which files the edit is of, from their repository's root.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from shared_memory.agents import ANOTHER_AGENT, agent_named
from shared_memory.locks import absolute, on_a_drive, slashed
from shared_memory.sessions import usable

CLAUDE = "claude"

# The header a hook names its coding agent in: the plugin's hooks and every kit's send it.
AGENT_HEADER = "X-Shared-Memory-Agent"


@dataclass(frozen=True)
class AgentHooks:
    """One coding agent's hooks as this server knows them: the agent's name, what its hooks send in `AGENT_HEADER`,
    and the answer format (`?format=`) its before-edit hook asks for. The plugin and each kit in `connection.py` send
    these, so a new agent is added here, with its kit beside the others."""

    name: str
    header: str
    format: str


CLAUDE_CODE = AgentHooks("Claude Code", "claude-code", CLAUDE)
CODEX = AgentHooks("Codex", "codex", CLAUDE)
GEMINI_CLI = AgentHooks("Gemini CLI", "gemini", "gemini")
COPILOT_CLI = AgentHooks("GitHub Copilot", "copilot", "copilot-cli")
CURSOR = AgentHooks("Cursor", "cursor", "cursor")
DEVIN = AgentHooks("Devin Desktop", "devin", "devin")
CLINE = AgentHooks("Cline", "cline", "cline")
AGENTS = (CLAUDE_CODE, CODEX, GEMINI_CLI, COPILOT_CLI, CURSOR, DEVIN, CLINE)

# The coding agent behind each answer format only one agent asks for, for a hook that sends no such header.
# Claude Code's format says nothing: Claude Code and Codex both ask for it, and Devin Desktop too on all but its
# before-edit hook.
_AGENT_OF_FORMAT = {
    each.format: each.name for each in AGENTS if [other.format for other in AGENTS].count(each.format) == 1
}


def agent_of(named: str | None, format: str | None) -> str | None:
    """The coding agent a hook call came from: the one its header names, or else the one its answer format belongs
    to. None when neither says. Like the name a tool call reports, it is only shown, never used to decide anything."""
    known = agent_named(named) if named and named.strip() else ANOTHER_AGENT
    if known != ANOTHER_AGENT:
        return known
    return _AGENT_OF_FORMAT.get((format or "").strip().lower())

# The fields of a tool's arguments that agents name the file being edited in: Claude Code's Edit and Write, Gemini
# CLI's write_file and replace and Cursor's Write send "file_path", Claude Code's NotebookEdit "notebook_path", and
# Copilot CLI's and Cline's edit tools "path".
_FILE_FIELDS = ("file_path", "notebook_path", "path")

# Copilot CLI and Cline name the tool beside its arguments and give every tool a "path", the ones that only read a
# file included, so for those two shapes the tool must be one that changes a file.
_COPILOT_CLI_EDIT_TOOLS = frozenset({"edit", "create"})
_CLINE_EDIT_TOOLS = frozenset({"write_to_file", "replace_in_file"})

# Codex edits files with apply_patch, whose one argument is the patch: each file it changes is named on a line of its
# own.
_PATCHED_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.MULTILINE)

# Where agents with no working folder in their payload name the folders that are open: Cursor and Cline.
_ROOTS_FIELDS = ("workspace_roots", "workspaceRoots")

# The fields agents put the member's prompt in. Claude Code, Cursor and Copilot send "prompt"; Copilot's session start
# sends the prompt a session opened with as "initialPrompt".
_PROMPT_FIELDS = ("prompt", "user_prompt", "userPrompt", "initial_prompt", "initialPrompt")

# The fields agents name the event in: Claude Code and VS Code send "hook_event_name", Cline sends "hookName".
_EVENT_FIELDS = ("hook_event_name", "hookEventName", "hookName")

# The fields agents tell one session from another in (ADR-0018): Claude Code, Codex and Gemini CLI send "session_id",
# Copilot CLI "sessionId", Cursor "conversation_id", and Cline the task's "taskId". Cursor's comes first because it is
# in every one of Cursor's payloads, where "session_id" is only in those for a session's start and end.
_SESSION_FIELDS = ("conversation_id", "conversationId", "session_id", "sessionId", "taskId")


def _claude(event: str, context: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}


def _copilot_cli(event: str, context: str) -> dict[str, Any]:
    return {"additionalContext": context}


def _cursor(event: str, context: str) -> dict[str, Any]:
    return {"additional_context": context}


def _cline(event: str, context: str) -> dict[str, Any]:
    # Cline reads the same answer for allowing the task to go on and for adding to it, so it always says cancel: false.
    return {"cancel": False, "contextModification": context}


def _claude_blocked(event: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": reason}
    }


def _gemini_blocked(event: str, reason: str) -> dict[str, Any]:
    return {"decision": "deny", "reason": reason}


def _devin_blocked(event: str, reason: str) -> dict[str, Any]:
    return {"decision": "block", "reason": reason}


def _copilot_cli_blocked(event: str, reason: str) -> dict[str, Any]:
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def _cursor_blocked(event: str, reason: str) -> dict[str, Any]:
    # Cursor's own field names: one message is shown to the person at the keyboard, the other is given to its agent.
    return {"permission": "deny", "user_message": reason, "agent_message": reason}


def _cline_blocked(event: str, reason: str) -> dict[str, Any]:
    return {"cancel": True, "errorMessage": reason}


Shape = Callable[[str, str], dict[str, Any]]


@dataclass(frozen=True)
class Family:
    """One answer format's two shapes, each given the event and a text: the one that adds context to a session, and
    the one that stops its agent before an edit."""

    answered: Shape
    blocked: Shape


_FAMILIES: dict[str, Family] = {
    CLAUDE: Family(_claude, _claude_blocked),
    GEMINI_CLI.format: Family(_claude, _gemini_blocked),
    DEVIN.format: Family(_claude, _devin_blocked),
    COPILOT_CLI.format: Family(_copilot_cli, _copilot_cli_blocked),
    CURSOR.format: Family(_cursor, _cursor_blocked),
    CLINE.format: Family(_cline, _cline_blocked),
}


def _named(format: str | None) -> str:
    """The family whose format was asked for, or Claude Code's for a name this server doesn't know."""
    name = (format or "").strip().lower()
    return name if name in _FAMILIES else CLAUDE


def answered(format: str | None, event: str, context: str) -> dict[str, Any]:
    """The body that carries this context into a session, shaped the way this family's hooks require."""
    return _FAMILIES[_named(format)].answered(event, context)


def blocked(format: str | None, event: str, reason: str) -> dict[str, Any]:
    """The body that stops this family's agent before its edit, and gives it the reason to tell its member."""
    return _FAMILIES[_named(format)].blocked(event, reason)


def edited_files(payload: Mapping[str, Any], root: str | None = None) -> list[str]:
    """The files an edit tool is about to change, each as a path from its repository's root: none when the payload
    names no file, and without any it names outside that root.

    One file, but for Codex's apply_patch, which may change several. Agents name a file by its absolute path or by a
    path from the folder they work in. The root is the one the hook itself names, where it does and the file is under
    it, or else the payload's working folder ("cwd") or one of the folders it says are open; the path from the root is
    what is left of the file's path after it. A relative path is read from the payload's working folder (its "cwd", or
    else the first folder it says is open), which is the root unless the hook named one above it; with no such folder,
    or none under the root, it is taken as written from the root. On a Windows drive the two are compared without
    regard to case, as Windows does.
    """
    given = _given_to_edit_tool(payload)
    if given is None:
        return []
    named = [given[field] for field in _FILE_FIELDS if isinstance(given.get(field), str)][:1]
    patch = given.get("command")
    if not named and isinstance(patch, str):
        named = _PATCHED_FILE.findall(patch)
    folders = _roots(payload, root)
    working = _roots(payload, None)[:1]
    files = (_from_root(file, folders, working) for file in named)
    return list(dict.fromkeys(file for file in files if file))


def _given_to_edit_tool(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """What the tool a before-edit payload is about was given, in whichever shape its agent sends it, or None when
    the payload shows no tool that changes a file."""
    given = payload.get("tool_input")
    if isinstance(given, Mapping):
        return given
    if "toolArgs" in payload:
        # Copilot CLI, which sends the arguments as an object or as the JSON text of one.
        given = payload["toolArgs"]
        if isinstance(given, str):
            try:
                given = json.loads(given)
            except ValueError:
                return None
        edits = payload.get("toolName") in _COPILOT_CLI_EDIT_TOOLS
        return given if edits and isinstance(given, Mapping) else None
    about = payload.get("preToolUse")
    if isinstance(about, Mapping):
        # Cline, which nests the tool and its parameters under the event's own name.
        given = about.get("parameters")
        edits = (about.get("tool") or about.get("toolName")) in _CLINE_EDIT_TOOLS
        return given if edits and isinstance(given, Mapping) else None
    return None


def _roots(payload: Mapping[str, Any], root: str | None) -> list[str]:
    """The folders a file's absolute path may be under, first to last: the root the hook names, and then what the
    payload names.

    The payload's folders stay behind the hook's root because a hook may name it from a folder that isn't the
    session's: Codex, Cursor and Cline ask git from wherever they run the hook's command, which their references
    don't promise is where the session works (#249). A file outside that root but inside the payload's folder is then
    named from the payload's, as it was before any hook named a root, rather than taken to be outside the repository.
    """
    named: list[Any] = [root, payload.get("cwd")]
    for field in _ROOTS_FIELDS:
        listed = payload.get(field)
        named += listed if isinstance(listed, list) else []
    return [folder for folder in named if isinstance(folder, str) and folder.strip()]


def _from_root(named: str, folders: list[str], working: list[str]) -> str | None:
    file = slashed(named)
    if not file:
        return None
    if not absolute(file):
        within = [slashed(folder) for folder in working if absolute(slashed(folder))]
        found = _from_root(f"{within[0].rstrip('/')}/{file}", folders, []) if within else None
        return found or file
    file = posixpath.normpath(file)
    for each in folders:
        folder = posixpath.normpath(slashed(each)).rstrip("/")
        if file.lower().startswith(folder.lower() + "/") if on_a_drive(folder) else file.startswith(folder + "/"):
            return file[len(folder) + 1 :]
    return None


def prompt_in(payload: Mapping[str, Any], depth: int = 3) -> str | None:
    """The member's prompt, from whichever shape its agent's hook sent it in: a field of the payload, a list of
    content parts, or a nested block, which is how Cline sends it (under "userPromptSubmit")."""
    for field in _PROMPT_FIELDS:
        if field in payload:
            text = _as_text(payload[field])
            if text:
                return text
    if depth > 1:
        for value in payload.values():
            if isinstance(value, Mapping):
                text = prompt_in(value, depth - 1)
                if text:
                    return text
    return None


def _as_text(value: Any) -> str | None:
    """A prompt as text, whether the agent sent a string or a list of content parts."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [
            part["text"]
            for part in value
            if isinstance(part, Mapping) and isinstance(part.get("text"), str) and part.get("type", "text") == "text"
        ]
        return "\n".join(parts).strip() or None
    return None


def event_in(payload: Mapping[str, Any], default: str) -> str:
    """The event an agent says it is hooking, to echo back as it wrote it, or this endpoint's own name for the event."""
    for field in _EVENT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def session_in(payload: Mapping[str, Any]) -> str | None:
    """The identifier of the session whose hook sent this payload, or None when it names none the server can keep."""
    for field in _SESSION_FIELDS:
        identifier = usable(payload.get(field))
        if identifier is not None:
            return identifier
    return None


def source_in(payload: Mapping[str, Any]) -> str | None:
    """Why a session-start hook fired (`startup`, `resume`, `clear`, `compact`), or None when the payload says none."""
    value = payload.get("source")
    return value.strip() if isinstance(value, str) and value.strip() else None


def notice(format: str | None, text: str) -> dict[str, Any]:
    """A word for the member rather than for the model, such as that Shared Memory is unavailable. Claude Code's format
    is the only one with a field for it; the rest are answered empty, which leaves their sessions untouched."""
    return {"systemMessage": text} if _named(format) == CLAUDE else {}
