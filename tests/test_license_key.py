"""A license key is checked offline: valid, tampered, lapsed and wrongly signed keys, and key versions (spec #416)."""

from __future__ import annotations

import socket
from datetime import date

import pytest

from shared_memory import license as licensing
from shared_memory.license import License, InvalidLicense, verify
from tests.license_keys import OTHER_PRIVATE, TEST_PUBLIC_KEYS, a_key

TODAY = date(2026, 11, 6)


def test_a_valid_key_says_who_it_is_for_how_many_and_until_when() -> None:
    found = verify(a_key(team="Acme", member_cap=10, key_id="k-7"), TEST_PUBLIC_KEYS)

    assert found == License("Acme", 10, date(2026, 9, 1), date(2027, 9, 1), "k-7")


def test_a_key_with_one_character_changed_is_refused() -> None:
    key = a_key(member_cap=5)
    head, payload, signature = key.split(".")
    other = a_key(member_cap=500).split(".")[1]

    with pytest.raises(InvalidLicense, match="signature"):
        verify(f"{head}.{other}.{signature}", TEST_PUBLIC_KEYS)
    with pytest.raises(InvalidLicense):
        verify(f"{head}.{payload}.{signature[:-2]}AA", TEST_PUBLIC_KEYS)


def test_a_key_signed_by_another_private_key_is_refused() -> None:
    from shared_memory.license import sign

    forged = sign(OTHER_PRIVATE, 1, License("Acme", 99, date(2026, 9, 1), date(2027, 9, 1), "k-x"))

    with pytest.raises(InvalidLicense, match="signature"):
        verify(forged, TEST_PUBLIC_KEYS)


def test_signing_key_versions_rotate() -> None:
    assert verify(a_key(version=1), TEST_PUBLIC_KEYS).member_cap == 5
    assert verify(a_key(version=2), TEST_PUBLIC_KEYS).member_cap == 5
    # A server that knows only the old version refuses a key from the new one.
    with pytest.raises(InvalidLicense, match="version 2"):
        verify(a_key(version=2), {1: TEST_PUBLIC_KEYS[1]})
    # And a key can't claim another version than the one it was signed under.
    claiming = a_key(version=2).replace("sm2.", "sm1.", 1)
    with pytest.raises(InvalidLicense, match="signature"):
        verify(claiming, TEST_PUBLIC_KEYS)


@pytest.mark.parametrize("text", ["", "hello", "sm1.only-two", "x1.a.b", "smx.a.b", "sm1.!!!.!!!"])
def test_text_that_is_not_a_key_is_refused(text: str) -> None:
    with pytest.raises(InvalidLicense):
        verify(text, TEST_PUBLIC_KEYS)


def test_the_built_in_public_key_refuses_a_test_key() -> None:
    with pytest.raises(InvalidLicense):
        verify(a_key())


def test_a_key_is_licensed_expiring_or_lapsed_by_its_date() -> None:
    found = verify(a_key(expires=date(2026, 12, 6)), TEST_PUBLIC_KEYS)

    assert found.status(date(2026, 11, 6)) == "expiring"  # exactly 30 days left
    assert found.status(date(2026, 11, 5)) == "licensed"
    assert found.status(date(2026, 12, 6)) == "expiring"  # the last day still counts
    assert found.status(date(2026, 12, 7)) == "lapsed"
    assert found.days_left(date(2026, 12, 1)) == 5


def test_checking_a_key_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_: object, **__: object) -> None:
        raise AssertionError("the license check opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)

    assert verify(a_key(), TEST_PUBLIC_KEYS).status(TODAY) == "licensed"
    assert licensing.PUBLIC_KEYS  # the built-in key is present
