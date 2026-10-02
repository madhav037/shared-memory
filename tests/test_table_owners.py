"""Each table is queried only by the module that owns it, and ADR numbers are unique.

`CODING_STANDARDS.md` says one module owns each table: a module that needs to know who leads a project or who may
reach it asks `Identity`. The code review of spec #220 found that rule broken in three places, which only a reviewer
caught. This test makes it mechanical. A table's owner is the module that creates it, except the tables `db.py`
creates for others: Identity's and the board's are listed in `OWNERS`. A query is any `FROM`, `JOIN`, `INTO` or
`UPDATE` naming the table; a foreign key's `REFERENCES` is not one.

The reads that predate the rule are listed in `EXISTING`. The test fails when a new one appears, and also when one
listed there has gone, so the list shrinks as #256 is done.

Two ADRs once took the number 0016 on the same day, from agents working in parallel, and main went red. The last test
keeps each number to one ADR.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON = ROOT / "src" / "shared_memory"
ADRS = ROOT / "docs" / "adr"

IDENTITY = ("teams", "members", "tokens", "projects", "repositories", "project_leads", "project_access")
BOARD = ("boards", "cards", "card_links", "card_comments")

#: Tables `db.py` creates on another module's behalf.
OWNERS = {
    **{table: "identity.py" for table in IDENTITY},
    **{table: "board.py" for table in BOARD},
    "console_sessions": "console_sessions.py",
    "console_sign_ins": "console_sessions.py",
    "audit_events": "audit.py",
}

#: Reads of another module's table from before the rule was checked. #256 moved the last of them behind Identity.
EXISTING: set[tuple[str, str]] = set()


def modules() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in PYTHON.glob("*.py")}


def owners(texts: dict[str, str]) -> dict[str, str]:
    created = {
        table: name
        for name, text in texts.items()
        for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text)
    }
    return created | OWNERS


def foreign_reads(texts: dict[str, str]) -> set[tuple[str, str]]:
    found = set()
    for table, owner in owners(texts).items():
        query = re.compile(rf"\b(?:FROM|JOIN|INTO|UPDATE)\s+{table}\b")
        found |= {(name, table) for name, text in texts.items() if name != owner and query.search(text)}
    return found


def test_no_module_queries_a_table_it_does_not_own() -> None:
    new = foreign_reads(modules()) - EXISTING
    assert not new, f"Ask the owning module instead of querying its table: {sorted(new)}"


def test_the_existing_foreign_reads_are_still_there() -> None:
    gone = EXISTING - foreign_reads(modules())
    assert not gone, f"No longer read, so take them out of EXISTING: {sorted(gone)}"


def test_each_adr_number_is_used_once() -> None:
    numbers: dict[str, list[str]] = {}
    for path in sorted(ADRS.glob("[0-9][0-9][0-9][0-9]-*.md")):
        numbers.setdefault(path.name[:4], []).append(path.name)
    taken_twice = {number: names for number, names in numbers.items() if len(names) > 1}
    assert not taken_twice, f"Renumber the later ADR to the next free number: {taken_twice}"
