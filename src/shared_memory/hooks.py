"""The adapter between the hook endpoints and each coding agent family's own hook format (ADR-0011).

Every agent's hooks post to the same endpoints and name, as ?format=, the family whose shape they can read:

- `claude`: `hookSpecificOutput`, for Claude Code, Codex, Gemini CLI, Devin Desktop and Copilot in VS Code;
- `copilot-cli`: `additionalContext` at the top level;
- `cursor`: `additional_context`, which only Cursor's session start can take in;
- `cline`: `contextModification`, beside the `cancel` that keeps the task going.

A format this server doesn't know, or none at all, is answered in Claude Code's shape, which is what these endpoints
have always answered. Nothing here ever refuses or raises: a hook that cannot be answered is answered emptily, so no
session is ever held up by the state of the team's memory.

The before-edit hook is the one that can stop its agent, and for one reason only: another active session holds the
file's lock. `blocked` shapes that answer for each family:

- `claude`: `permissionDecision: "deny"` and its reason inside `hookSpecificOutput`;
- `copilot-cli`: the same two fields at the top level;
- `cursor`: `permission: "deny"`, with the reason once for its agent and once for its member;
- `cline`: `cancel: true` with an `errorMessage`.

An allowed edit is answered emptily in every family, which leaves the agent's own permission rules to decide as if
the hook weren't there. `edited_file` reads which file the edit is of, from its repository's root.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Mapping
from typing import Any

from shared_memory.sessions import usable

CLAUDE = "claude"

# The fields of a tool's input that agents name the file being edited in: Claude Code's Edit and Write send
# "file_path", and its NotebookEdit "notebook_path".
_FILE_FIELDS = ("file_path", "notebook_path")

_DRIVE = re.compile(r"^[A-Za-z]:")

# The fields agents put the member's prompt in. Claude Code, Cursor and Copilot send "prompt"; Copilot's session start
# sends the prompt a session opened with as "initialPrompt".
_PROMPT_FIELDS = ("prompt", "user_prompt", "userPrompt", "initial_prompt", "initialPrompt")

# The fields agents name the event in: Claude Code and VS Code send "hook_event_name", Cline sends "hookName".
_EVENT_FIELDS = ("hook_event_name", "hookEventName", "hookName")

# The fields agents tell one session from another in (ADR-0018): Claude Code, Codex and Gemini CLI send "session_id",
# Copilot CLI "sessionId", Cursor "conversation_id", and Cline the task's "taskId".
_SESSION_FIELDS = ("session_id", "sessionId", "conversation_id", "conversationId", "taskId")


def _claude(event: str, context: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}


def _copilot_cli(event: str, context: str) -> dict[str, Any]:
    return {"additionalContext": context}


def _cursor(event: str, context: str) -> dict[str, Any]:
    return {"additional_context": context}


def _cline(event: str, context: str) -> dict[str, Any]:
    # Cline reads the same answer for allowing the task to go on and for adding to it, so it always says cancel: false.
    return {"cancel": False, "contextModification": context}


_FORMATS: dict[str, Callable[[str, str], dict[str, Any]]] = {
    CLAUDE: _claude,
    "copilot-cli": _copilot_cli,
    "cursor": _cursor,
    "cline": _cline,
}


def _named(format: str | None) -> str:
    """The family whose format was asked for, or Claude Code's for a name this server doesn't know."""
    name = (format or "").strip().lower()
    return name if name in _FORMATS else CLAUDE


def answered(format: str | None, event: str, context: str) -> dict[str, Any]:
    """The body that carries this context into a session, shaped the way this family's hooks require."""
    return _FORMATS[_named(format)](event, context)


def _claude_blocked(event: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": reason}
    }


def _copilot_cli_blocked(event: str, reason: str) -> dict[str, Any]:
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def _cursor_blocked(event: str, reason: str) -> dict[str, Any]:
    # Cursor's own field names: one message is shown to the person at the keyboard, the other is given to its agent.
    return {"permission": "deny", "user_message": reason, "agent_message": reason}


def _cline_blocked(event: str, reason: str) -> dict[str, Any]:
    return {"cancel": True, "errorMessage": reason}


_BLOCKED: dict[str, Callable[[str, str], dict[str, Any]]] = {
    CLAUDE: _claude_blocked,
    "copilot-cli": _copilot_cli_blocked,
    "cursor": _cursor_blocked,
    "cline": _cline_blocked,
}


def blocked(format: str | None, event: str, reason: str) -> dict[str, Any]:
    """The body that stops this family's agent before its edit, and gives it the reason to tell its member."""
    return _BLOCKED[_named(format)](event, reason)


def edited_file(payload: Mapping[str, Any], root: str | None = None) -> str | None:
    """The file an edit tool is about to change, as a path from its repository's root, or None when the payload names
    no file or names one outside that root.

    Agents name the file by its absolute path. The root is the one the hook itself names, where it does, or else the
    payload's working folder ("cwd"); the path from the root is what is left of the file's path after it. A path that
    is already relative is taken as written from the root. On a Windows drive the two are compared without regard to
    case, as Windows does.
    """
    given = payload.get("tool_input")
    if not isinstance(given, Mapping):
        return None
    named = next((given[field] for field in _FILE_FIELDS if isinstance(given.get(field), str)), "")
    file = named.strip().replace("\\", "/")
    if not file:
        return None
    if not file.startswith("/") and not _DRIVE.match(file):
        return file
    cwd = payload.get("cwd")
    folder = root if root and root.strip() else cwd if isinstance(cwd, str) else ""
    folder = folder.strip().replace("\\", "/")
    if not folder:
        return None
    file, folder = posixpath.normpath(file), posixpath.normpath(folder).rstrip("/")
    within = file.lower().startswith(folder.lower() + "/") if _DRIVE.match(folder) else file.startswith(folder + "/")
    return file[len(folder) + 1 :] if within else None


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


def notice(format: str | None, text: str) -> dict[str, Any]:
    """A word for the member rather than for the model, such as that Shared Memory is unavailable. Claude Code's format
    is the only one with a field for it; the rest are answered empty, which leaves their sessions untouched."""
    return {"systemMessage": text} if _named(format) == CLAUDE else {}
