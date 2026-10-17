"""Which tools and prompts an agent is listed. Listing is presentation: every tool still checks for itself what its
caller may do."""

from __future__ import annotations

from dataclasses import dataclass

from shared_memory.agents import CLAUDE_CODE
from shared_memory.identity import Caller

# The tools only the team's owner and its admins can use (`Identity._require_admin`).
ADMIN_TOOLS = frozenset({"add_member", "remove_member", "reissue_token"})

# The tools that act on a card already on the board; `board` and `add_card` are always listed.
CARD_TOOLS = frozenset({"update_card", "claim_card", "comment_card", "delete_card"})


@dataclass(frozen=True)
class ProjectState:
    """What the caller's project and repository hold that decides what is listed to them."""

    has_cards: bool = False
    # The member has promoted an import from the repository their session works in.
    has_imported: bool = False


def is_listed_to(name: str, caller: Caller, state: ProjectState) -> bool:
    """Whether a tool or prompt is listed to this caller. A rule for a name goes here, one per name it hides."""
    if name in ADMIN_TOOLS:
        return caller.member.is_owner or caller.member.is_admin
    if name in CARD_TOOLS:
        return state.has_cards
    if name == "onboard":
        return not state.has_imported
    if name == "guide":
        # Claude Code has the skill itself. An agent that reports no name, or one we don't know, may not, so it is
        # listed.
        return caller.agent != CLAUDE_CODE
    return True
