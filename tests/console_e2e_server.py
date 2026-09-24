"""The server the browser journeys run against: a real server, a fake GitHub, and a team to sign in to."""

from __future__ import annotations

import tempfile
from pathlib import Path

from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import REPO_ROOT, FakeGitHub, RunningServer, Session, TestClock, fresh_database

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

        # A second project memory, and a challenge against it waiting for the owner to decide.
        staging = in_project.call(
            "remember",
            title="Staging resets nightly",
            summary="The staging database is wiped every night.",
            type="gotcha",
            body="The staging database is wiped and reseeded every night.",
        )
        challenged = in_project.call("promote", path=staging["path"], level="project")["path"]
        dana_token = owner.call(
            "add_member", employee_id="emp-dana", name="Raj Raiser", github="dana"
        )["personal_token"]
        dana = Session(server, dana_token).in_project(project, "billing-api")
        offered = dana.call(
            "remember",
            title="Staging resets at 02:17 UTC",
            summary="The staging database is wiped every night at 02:17 UTC.",
            type="gotcha",
            body="The staging database is wiped and reseeded every night at 02:17 UTC, not at midnight.",
        )
        similar = dana.call("promote", path=offered["path"], level="project")
        dana.call(
            "promote",
            path=offered["path"],
            level="project",
            reference=similar["reference"],
            resolutions={
                one["path"]: ("supersede" if one["path"] == challenged else "keep_both") for one in similar["similar"]
            },
        )
        print(f"console server on {server.url}, fake GitHub on {github.url}, project {project}", flush=True)
        try:
            server.join()
        except KeyboardInterrupt:
            pass
