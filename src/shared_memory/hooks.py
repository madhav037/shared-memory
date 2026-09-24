"""The adapter between the two hook endpoints and each coding agent family's own hook format (ADR-0011).

Every agent's hooks post to the same two endpoints and name, as ?format=, the family whose shape they can read:

- `claude`: `hookSpecificOutput`, for Claude Code, Codex, Gemini CLI, Devin Desktop and Copilot in VS Code;
- `copilot-cli`: `additionalContext` at the top level;
- `cursor`: `additional_context`, which only Cursor's session start can take in;
- `cline`: `contextModification`, beside the `cancel` that keeps the task going.

A format this server doesn't know, or none at all, is answered in Claude Code's shape, which is what these endpoints
have always answered. Nothing here ever refuses or raises: a hook that cannot be answered is answered emptily, so no
session is ever held up by the state of the team's memory.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

CLAUDE = "claude"

# The fields agents put the member's prompt in. Claude Code, Cursor and Copilot send "prompt"; Copilot's session start
# sends the prompt a session opened with as "initialPrompt".
_PROMPT_FIELDS = ("prompt", "user_prompt", "userPrompt", "initial_prompt", "initialPrompt")

# The fields agents name the event in: Claude Code and VS Code send "hook_event_name", Cline sends "hookName".
_EVENT_FIELDS = ("hook_event_name", "hookEventName", "hookName")


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


def notice(format: str | None, text: str) -> dict[str, Any]:
    """A word for the member rather than for the model, such as that Shared Memory is unavailable. Claude Code's format
    is the only one with a field for it; the rest are answered empty, which leaves their sessions untouched."""
    return {"systemMessage": text} if _named(format) == CLAUDE else {}
