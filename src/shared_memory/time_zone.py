"""Time zones (CONTEXT.md): the zone a member's times are shown in.

A member has a chosen time zone, which they pick in the console, and a detected one, which the console reports from
their browser after they sign in. Both are IANA names, kept by `Identity`. The zone a warning is read in is the chosen
one, else the detected one, else the session's UTC offset (#592), else none, when a warning's times stay relative.

- `names()`: every IANA name the server knows, the only names a member may choose or have detected.
- `checked(name)`: the name, or `Refused` when it is no time zone (`NotATimeZone`).
- `MemberTimeZone`: a member's chosen and detected names.
- `used(member, utc_offset_minutes)`: the zone a warning for this member's session is read in, or None.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone, tzinfo
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

from shared_memory.errors import Refused


class NotATimeZone(Refused):
    """A name that is no IANA time zone the server knows."""


@cache
def names() -> tuple[str, ...]:
    """Every IANA time zone name the server knows, sorted."""
    return tuple(sorted(available_timezones()))


def checked(name: str) -> str:
    """The name, if it is a time zone the server knows."""
    if name not in _known():
        raise NotATimeZone(f"{name!r} isn't a time zone. Choose one such as Europe/London or Asia/Kolkata.")
    return name


@cache
def _known() -> frozenset[str]:
    return frozenset(names())


@dataclass(frozen=True)
class MemberTimeZone:
    """A member's time zone as kept: the one they chose, if any, and the one detected for them, if any."""

    chosen: str | None
    detected: str | None

    @property
    def name(self) -> str | None:
        """The member's own zone: the chosen one, else the detected one."""
        return self.chosen or self.detected


def used(member: MemberTimeZone, utc_offset_minutes: int | None = None) -> tzinfo | None:
    """The zone a warning for a member's session is read in: the member's own zone, else the session's UTC offset its
    hook reported (#592), else None, when times stay relative. A name no longer known counts as none."""
    if member.name is not None and member.name in _known():
        return ZoneInfo(member.name)
    if utc_offset_minutes is not None:
        return timezone(timedelta(minutes=utc_offset_minutes))
    return None
