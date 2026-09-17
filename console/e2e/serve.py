"""The server the browser journeys run against: a real server on a database made for the run."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import uvicorn  # noqa: E402

from shared_memory.app import build_app  # noqa: E402
from shared_memory.config import Settings  # noqa: E402
from tests.support import fresh_database  # noqa: E402

if __name__ == "__main__":
    settings = Settings(
        database_url=fresh_database("shared_memory_console_e2e"),
        memory_root=Path(tempfile.mkdtemp(prefix="console-e2e-")) / "memory",
        model_cache=REPO_ROOT / ".cache" / "fastembed",
    )
    uvicorn.run(build_app(settings), host="127.0.0.1", port=8123, log_level="warning")
