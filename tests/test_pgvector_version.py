"""The tests stop at once on a test Postgres whose pgvector is too old (#531), rather than failing by the hundred."""

from __future__ import annotations

import pytest

from tests.support import PGVECTOR_NEEDED, pgvector_too_old


def test_the_needed_pgvector_is_0_8() -> None:
    assert PGVECTOR_NEEDED == (0, 8)


@pytest.mark.parametrize("found", ["0.8.0", "0.8.1", "0.9.0", "1.0.0", "0.10.2"])
def test_a_pgvector_of_0_8_or_later_passes(found: str) -> None:
    assert pgvector_too_old(found) is None


@pytest.mark.parametrize("found", ["0.6.0", "0.7.4", "0.5.1"])
def test_a_pgvector_older_than_0_8_names_the_version_needed_and_the_one_found(found: str) -> None:
    assert pgvector_too_old(found) == f"pgvector 0.8 or later is needed (found {found})"


def test_a_postgres_without_pgvector_is_stopped_too() -> None:
    assert pgvector_too_old(None) == "pgvector 0.8 or later is needed (found none)"
