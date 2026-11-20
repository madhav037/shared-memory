"""The one-off move of company memory from the folder it had while the top level was called team (ADR-0031, #625).

Company memory was kept under `team/` in each company's folder; it is kept under `company/`. A server that still holds
`team/` moves it as it sets up, before any worker serves, in one commit by the server, so each memory's history goes on
at its new path (`history.py`). In that same commit every header naming a moved memory (`exception_to`, `replaces`,
`superseded_by`) names its new path, and each moved folder's index its new name. In the commit's database transaction,
each module holding memory paths in its tables moves them: the search index, tied files, pins, challenges, when memory
was last used, card links, imports and what recall has told each session.

A promotion or a known issue save waiting on its reference across the upgrade starts again: those references name the
similar memories found, and are not moved. The audit log keeps the paths it recorded, as it keeps everything as it was.
Once nothing is left under `team/` this does nothing, so it runs on every setup. So does saying company memory's level
as `company` (#626) in each table keeping a memory's level, where it was kept as `team`.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from shared_memory import board, briefing, challenges, index, lifecycle, recall, tied, uses
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.memory import COMPANY_FOLDER, COMPANY_LEVEL, INDEX_NAME, Memory
from shared_memory.store import MemoryStore

log = logging.getLogger("shared_memory")

OLD_FOLDER = "team"
# The level company memory had in each table keeping one, before the rename's migrate step (#626).
OLD_LEVEL = "team"
# The header fields that name another memory by its path.
_NAMING = ("exception_to", "replaces", "superseded_by")
_MESSAGE = (
    "Move team memory to company memory\n\nThe top level of memory is the company (ADR-0031): its memory moves from "
    "team/ to company/ with its history.\n"
)


def moved(path: str) -> str:
    """Where a memory path is after the move."""
    pure = PurePosixPath(path)
    if pure.parts[:1] == (OLD_FOLDER,):
        return str(PurePosixPath(COMPANY_FOLDER, *pure.parts[1:]))
    return path


def rewritten(path: PurePosixPath, text: str) -> str:
    """A file's text after the move: an index names its folder anew, and a memory names each moved memory anew."""
    if path == PurePosixPath(INDEX_NAME):
        # The company folder's own index lists its folders by name, in order (`store._write_index`).
        lines = text.split("\n")
        listed = f"- [{OLD_FOLDER}/]({OLD_FOLDER}/{INDEX_NAME})"
        if listed not in lines:
            return text
        lines[lines.index(listed)] = f"- [{COMPANY_FOLDER}/]({COMPANY_FOLDER}/{INDEX_NAME})"
        start = lines.index("## Folders") + 2
        end = next((at for at in range(start, len(lines)) if not lines[at].startswith("- [")), len(lines))
        lines[start:end] = sorted(lines[start:end])
        return "\n".join(lines)
    if path.name == INDEX_NAME:
        heading, newline, rest = text.partition("\n")
        if heading.startswith(f"# {OLD_FOLDER}"):
            return f"# {moved(heading[2:])}{newline}{rest}"
        return text
    if path.suffix != ".md":
        return text
    try:
        memory = Memory.from_text(text)
    except Refused:
        return text  # not a memory: left as it is
    named = {field: getattr(memory, field) for field in _NAMING}
    renamed = {field: moved(value) if value is not None else None for field, value in named.items()}
    if renamed == named:
        return text
    for field, value in renamed.items():
        setattr(memory, field, value)
    return memory.to_text()


def move_company_memory(db: Database, store: MemoryStore) -> None:
    """Move every company's company memory out of `team/` into `company/`, if any is left there."""

    def move_paths() -> None:
        with db.transaction() as conn:
            for module in (index, tied, briefing, challenges, uses, board, lifecycle, recall):
                module.move_paths(conn, OLD_FOLDER, COMPANY_FOLDER)

    companies = store.move_folder(OLD_FOLDER, COMPANY_FOLDER, rewritten, _MESSAGE, move_paths)
    if companies:
        log.info("Moved team memory to company memory for %d company folder(s)", len(companies))


def rename_company_level(db: Database) -> None:
    """Say company memory's level as `company` in every table that keeps a memory's level, where a server from before
    the rename's migrate step (#626) kept it as `team`. Nothing once it has run, so it runs on every setup."""
    with db.transaction() as conn:
        for module in (index, tied, briefing, challenges, lifecycle):
            module.rename_level(conn, OLD_LEVEL, COMPANY_LEVEL)
