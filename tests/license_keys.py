"""TEST-ONLY signing keys for license keys. Never a production key: the seeds below are public, so anything signed with
them is worthless against a real server, whose built-in public key (license.PUBLIC_KEYS) is a different pair.

The browser journeys sign with the same first seed (console/e2e/license.ts)."""

from __future__ import annotations

from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from shared_memory.license import License, sign

TEST_SEED = bytes(range(32))
OTHER_SEED = bytes(range(32, 64))

TEST_PRIVATE = Ed25519PrivateKey.from_private_bytes(TEST_SEED)
OTHER_PRIVATE = Ed25519PrivateKey.from_private_bytes(OTHER_SEED)


def public_of(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


# What the server under test trusts: signing key version 1 is TEST_PRIVATE's, version 2 is OTHER_PRIVATE's.
TEST_PUBLIC_KEYS = {1: public_of(TEST_PRIVATE), 2: public_of(OTHER_PRIVATE)}


def a_key(
    team: str = "Acme",
    member_cap: int = 5,
    issued: date = date(2026, 9, 1),
    expires: date = date(2027, 9, 1),
    key_id: str = "k-1",
    version: int = 1,
) -> str:
    private = OTHER_PRIVATE if version == 2 else TEST_PRIVATE
    return sign(private, version, License(team, member_cap, issued, expires, key_id))
