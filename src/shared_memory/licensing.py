"""Which license key the server is running under, and what it sets (spec #416).

The key comes from the server-wide settings an admin installed on the Team page, or else from `SHARED_MEMORY_LICENSE_KEY`.
A key whose signature checks out sets the member cap, even once it has lapsed. On a self-hosted server nothing else
depends on it: a missing, lapsed or invalid key only shows admins a banner, and memory, MCP tools and hooks never look at
it. A hosted server's key that has lapsed makes the server read-only: every change to memory is refused, and reading
keeps working (ADR-0022). No network call is made, ever (license.py only verifies).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from shared_memory.audit import LICENSE_INSTALLED, Audit
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Member
from shared_memory.license import PUBLIC_KEYS, InvalidLicense, License, verify

# Several workers share one database: how long one remembers the key before reading it again.
CACHED = timedelta(seconds=5)


@dataclass(frozen=True)
class Current:
    """The license the server is under. `status` is licensed, expiring, lapsed, read-only (a hosted server's key has
    lapsed), invalid (a key was given but can't be trusted) or unlicensed (none was given)."""

    status: str
    license: License | None
    reason: str | None
    source: str | None
    days_left: int | None


class Licenses:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        audit: Audit,
        clock: Clock,
        public_keys: Mapping[int, bytes] = PUBLIC_KEYS,
    ) -> None:
        self.settings = settings
        self._db = db
        self._audit = audit
        self._clock = clock
        self._public_keys = public_keys
        self._known: tuple[datetime, Current] | None = None

    def current(self) -> Current:
        now = self._clock()
        if self._known is not None and now - self._known[0] < CACHED:
            return self._known[1]
        with self._db.transaction() as conn:
            row = conn.execute("SELECT key FROM license_settings WHERE id = 1").fetchone()
        installed = row["key"] if row is not None else None
        text, source = (installed, "console") if installed else (self.settings.license_key.strip(), "environment")
        if not text:
            found = Current("unlicensed", None, "No license key is installed.", None, None)
        else:
            try:
                held = verify(text, self._public_keys)
            except InvalidLicense as invalid:
                found = Current("invalid", None, str(invalid), source, None)
            else:
                today = now.date()
                found = Current(held.status(today), held, None, source, held.days_left(today))
        self._known = (now, found)
        return found

    def member_cap(self) -> int | None:
        """The server's member cap: the key's, if it has a trustworthy one, otherwise `SHARED_MEMORY_MEMBER_CAP`."""
        held = self.current().license
        return held.member_cap if held is not None else self.settings.member_cap

    def ensure_writable(self) -> None:
        """Refuse a change to memory while the server is read-only: its key is a hosted server's, and has lapsed. A
        self-hosted server is never read-only (ADR-0022)."""
        current = self.current()
        if current.status == "read-only" and current.license is not None:
            raise Refused(
                f"This hosted server's license key lapsed on {current.license.expires.isoformat()}, so the server is "
                "read-only: memory can still be read and searched, but nothing can be saved or changed. Paying for "
                "your team's plan restores it, with all its memory."
            )

    def install(self, admin: Member, text: str) -> Current:
        """Keep this key server-wide, as an owner or an admin, and record who did it."""
        if not (admin.is_owner or admin.is_admin):
            raise Refused("Only the team's owner and its admins can install a license key.")
        try:
            held = verify(text, self._public_keys)
        except InvalidLicense as invalid:
            raise Refused(str(invalid)) from None
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO license_settings (id, key) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET key = EXCLUDED.key",
                (text.strip(),),
            )
        self._known = None
        self._audit.record(
            LICENSE_INSTALLED,
            member=admin,
            detail={
                "team": held.team,
                "member_cap": held.member_cap,
                "expires": held.expires.isoformat(),
                "key_id": held.key_id,
            },
        )
        return self.current()

    def clear(self) -> None:
        """Remove the installed key, so the environment's (if any) stands. For tests."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM license_settings")
        self._known = None
