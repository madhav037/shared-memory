"""A project's ID is its name plus a random suffix, and a clash of suffixes never reaches the member."""

from __future__ import annotations

from itertools import chain, repeat

import pytest

from shared_memory import identity
from tests.support import Team


class Suffixes:
    """Stands in for `secrets` in identity.py, handing out the suffixes in order, then fresh ones."""

    def __init__(self, first: list[str]) -> None:
        self._fresh = (f"{n:08x}" for n in range(0xA0000000, 0xB0000000))
        self._next = chain(first, repeat(None))

    def token_hex(self, _nbytes: int) -> str:
        return next(self._next) or next(self._fresh)


def test_two_projects_whose_suffixes_clash_both_get_created(monkeypatch: pytest.MonkeyPatch, team: Team) -> None:
    monkeypatch.setattr(identity, "secrets", Suffixes(["c0ffee00", "c0ffee00"]))
    owner = team.owner()

    first = owner.call("create_project", name="Clashing name")["project_id"]
    second = owner.call("create_project", name="Clashing name")["project_id"]

    assert first == "clashing-name-c0ffee00"
    assert second != first
    assert second.startswith("clashing-name-")
