"""Which tools an agent is listed. Listing is presentation: every tool still checks for itself what its caller may do."""

from __future__ import annotations

from shared_memory.identity import Caller

# The tools only the team's owner and its admins can use (`Identity._require_admin`).
ADMIN_TOOLS = frozenset({"add_member", "remove_member", "reissue_token"})


def is_listed_to(tool: str, caller: Caller) -> bool:
    """Whether a tool is listed to this caller. A rule for a tool goes here, one per tool it hides."""
    if tool in ADMIN_TOOLS:
        return caller.member.is_owner or caller.member.is_admin
    return True
