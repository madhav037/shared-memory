"""Which coding agent a session runs in, from the name the agent reports for itself when it connects.

The name is whatever the agent chooses to send, so it is only ever shown and recorded, never used to decide what a
session may do.
"""

from __future__ import annotations

ANOTHER_AGENT = "another agent"

# Checked in order: Cursor reports "cursor-vscode", which must not be taken for VS Code.
_KNOWN: list[tuple[tuple[str, ...], str]] = [
    (("cursor",), "Cursor"),
    (("windsurf", "devin"), "Devin Desktop"),
    (("cline",), "Cline"),
    (("gemini",), "Gemini CLI"),
    (("codex",), "Codex"),
    (("claude-code", "claude code"), "Claude Code"),
    (("visual studio code", "visual-studio-code", "vscode", "copilot"), "GitHub Copilot"),
]


def agent_named(reported: str | None) -> str:
    """The coding agent a reported client name belongs to, or "another agent" for any name not known."""
    name = (reported or "").strip().lower()
    for markers, known in _KNOWN:
        if any(marker in name for marker in markers):
            return known
    return ANOTHER_AGENT
