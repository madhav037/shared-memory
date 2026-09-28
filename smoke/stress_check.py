"""Whether a team's memory files, git and search index agree: the stress test's closing check (docs/stress-test.md).

It runs where the server runs, since it reads the memory folder and the database directly, so it needs nothing beyond
the standard library and psycopg, which the server's image has:

    SHARED_MEMORY_DATABASE_URL=... python stress_check.py <memory folder> <team>

It prints one JSON object.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


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
    uncommitted = git(root, "status", "--porcelain", "--", team).stdout.splitlines()
    fsck = git(root, "fsck", "--no-progress")
    return {
        "memory_files": len(files),
        "indexed_memories": len(indexed),
        "not_searchable": sorted(files - indexed),
        "searchable_but_gone": sorted(indexed - files),
        "uncommitted": uncommitted,
        "git_fsck_ok": fsck.returncode == 0,
        "git_fsck_output": (fsck.stdout + fsck.stderr).strip()[:2000],
        "commits": int(git(root, "rev-list", "--count", "HEAD").stdout.strip() or 0),
    }


def main() -> None:
    root, team = Path(sys.argv[1]), sys.argv[2]
    print(json.dumps(check(root, team, os.environ["SHARED_MEMORY_DATABASE_URL"])))


if __name__ == "__main__":
    main()
