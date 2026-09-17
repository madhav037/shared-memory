"""The server the browser journeys run against: a real server, a fake GitHub, and a team to sign in to."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from anyio.from_thread import start_blocking_portal  # noqa: E402

from shared_memory.app import build_app  # noqa: E402
from shared_memory.config import Settings  # noqa: E402
from tests.support import FakeGitHub, RunningServer, Session, TestClock, fresh_database  # noqa: E402

CONSOLE = "http://127.0.0.1:4173"
PORT = 8123

if __name__ == "__main__":
    memory = Path(tempfile.mkdtemp(prefix="console-e2e-")) / "memory"
    with start_blocking_portal() as portal:
        github = FakeGitHub(portal, Settings("", memory, memory), port=8124)
        github.as_(1, "olive")
        settings = Settings(
            database_url=fresh_database("shared_memory_console_e2e"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=github.url,
            github_api_url=github.url,
            console_url=CONSOLE,
        )
        server = RunningServer(build_app(settings, clock=TestClock()), settings, TestClock(), portal, port=PORT)
        printed = server.run_cli(
            "setup", "--team", "acme", "--owner-employee-id", "E1001", "--owner-name", "Olive Owner",
            "--owner-github", "olive",
        )  # fmt: skip
        token = next(
            line.split(":", 1)[1].strip() for line in printed.splitlines() if line.startswith("Owner personal")
        )
        # A project with one memory in it, so the browsing journeys have something to read.
        owner = Session(server, token)
        project = owner.call("create_project", name="Billing", repository="billing-api")["project_id"]
        in_project = owner.in_project(project, "billing-api")
        saved = in_project.call(
            "remember",
            title="Use pnpm, not npm",
            summary="Every package in billing is managed with pnpm, never npm.",
            type="convention",
            body="We use pnpm for every package. npm creates a second lockfile and CI rejects it.",
        )
        in_project.call("promote", path=saved["path"], level="project")
        print(f"console server on {server.url}, fake GitHub on {github.url}, project {project}", flush=True)
        try:
            server.join()
        except KeyboardInterrupt:
            pass
