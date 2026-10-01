"""Onboarding: the steps a member's coding agent follows to import their existing setup into memory.

The server only hands the steps over. Reading the sources, cutting them into memories and judging what contradicts
what happen in the member's session (ADR-0004), with the same tools any session uses.
"""

from __future__ import annotations

from importlib import resources


def steps() -> str:
    """The onboarding steps, the one text behind the `onboard` tool and the `onboard` prompt. The skills only point
    at it, so every coding agent follows the same steps."""
    return resources.files("shared_memory").joinpath("onboarding.md").read_text(encoding="utf-8")
