"""The zone a warning is read in (spec #585): the member's chosen time zone, else the detected one, else the session's
UTC offset, else none. Pure, so tested here without a server; what a member sees is tested through the gates."""

from __future__ import annotations

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from shared_memory.time_zone import MemberTimeZone, NotATimeZone, checked, names, used


def test_the_chosen_zone_wins_over_the_detected_one() -> None:
    assert used(MemberTimeZone("Asia/Kolkata", "America/New_York")) == ZoneInfo("Asia/Kolkata")


def test_the_detected_zone_stands_in_while_none_is_chosen() -> None:
    assert used(MemberTimeZone(None, "America/New_York")) == ZoneInfo("America/New_York")


def test_the_sessions_utc_offset_stands_in_for_a_member_with_no_zone() -> None:
    assert used(MemberTimeZone(None, None), utc_offset_minutes=330) == timezone(timedelta(minutes=330))
    assert used(MemberTimeZone(None, "Europe/Berlin"), utc_offset_minutes=330) == ZoneInfo("Europe/Berlin")


def test_with_no_zone_at_all_times_stay_relative() -> None:
    assert used(MemberTimeZone(None, None)) is None


def test_a_name_that_is_no_time_zone_is_refused() -> None:
    assert checked("Europe/Berlin") == "Europe/Berlin"
    assert "Europe/Berlin" in names()
    for wrong in ("Mars/Olympus_Mons", "UTC+5", "", "../etc/passwd"):
        with pytest.raises(NotATimeZone):
            checked(wrong)
