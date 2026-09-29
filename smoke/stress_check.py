"""Whether a team's memory files, git and search index agree: the stress test's closing check (docs/stress-test.md).

It runs where the server runs, since it reads the memory folder and the database directly, so it needs nothing beyond
the standard library and psycopg, which the server's image has:

    SHARED_MEMORY_DATABASE_URL=... python stress_check.py <memory folder> <team>

It prints one JSON object.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def uncommitted(root: Path, team: str) -> list[str]:
    """Every file in the team's folder that differs from main's last commit, or is on only one side of it.

    Compared with the commit's tree, not git's index, which saves don't keep up to date (ADR-0012).
    """
    committed: dict[str, str] = {}
    for entry in filter(None, git(root, "ls-tree", "-r", "-z", "HEAD", "--", team).stdout.split("\0")):
        meta, path = entry.split("\t", 1)
        committed[path] = meta.split()[2]
    folder = root / team
    on_disk: dict[str, str] = {}
    for file in folder.rglob("*") if folder.is_dir() else []:
        if file.is_file():
            data = file.read_bytes()
            on_disk[f"{team}/{file.relative_to(folder).as_posix()}"] = hashlib.sha1(
                b"blob %d\0" % len(data) + data
            ).hexdigest()
    return sorted(path for path in committed.keys() | on_disk.keys() if committed.get(path) != on_disk.get(path))


def check(root: Path, team: str, database_url: str) -> dict[str, Any]:
    team_dir = root / team
    # Every folder has an index.md the server writes for it; the memories are the other Markdown files.
    files = {
        path.relative_to(team_dir).as_posix()
        for path in team_dir.rglob("*.md")
        if path.name != "index.md" and ".git" not in path.parts
    }
    with psycopg.connect(database_url) as conn:
        indexed = {row[0] for row in conn.execute("SELECT DISTINCT path FROM sections WHERE team = %s", (team,))}
    fsck = git(root, "fsck", "--no-progress")
    return {
        "memory_files": len(files),
        "indexed_memories": len(indexed),
        "not_searchable": sorted(files - indexed),
        "searchable_but_gone": sorted(indexed - files),
        "uncommitted": uncommitted(root, team),
        "git_fsck_ok": fsck.returncode == 0,
        "git_fsck_output": (fsck.stdout + fsck.stderr).strip()[:2000],
        "commits": int(git(root, "rev-list", "--count", "HEAD").stdout.strip() or 0),
    }


def main() -> None:
    root, team = Path(sys.argv[1]), sys.argv[2]
    print(json.dumps(check(root, team, os.environ["SHARED_MEMORY_DATABASE_URL"])))


if __name__ == "__main__":
    main()
