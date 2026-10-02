"""The server the browser journeys run against: a real server, a fake GitHub, and a team to sign in to."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

import psycopg
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from tests.support import (
    REPO_ROOT,
    FakeGitHub,
    RunningServer,
    Session,
    TestClock,
    challenge,
    fresh_database,
    promote_keeping_both,
    promote_now,
)

CONSOLE = "http://127.0.0.1:4273"
PORT = 8123
# The fake GitHub's port. It is not 8124: a local sign-in stack has run its own stand-in GitHub there, and the journeys
# then could not start at all. Set SHARED_MEMORY_E2E_GITHUB_PORT when something else holds this one too; the browser
# side reads the same variable (console/e2e/helpers.ts).
DEFAULT_GITHUB_PORT = 8126


def github_port(env: Mapping[str, str] = os.environ) -> int:
    return int(env.get("SHARED_MEMORY_E2E_GITHUB_PORT", DEFAULT_GITHUB_PORT))

if __name__ == "__main__":
    memory = Path(tempfile.mkdtemp(prefix="console-e2e-")) / "memory"
    with start_blocking_portal() as portal:
        github = FakeGitHub(portal, Settings("", memory, memory), port=github_port())
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
            "setup", "--team", "acme", "--owner-member-id", "E1001", "--owner-name", "Olive Owner",
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
        pnpm = in_project.call("promote", path=saved["path"], level="project")["path"]

        # A second project memory, and a challenge against it waiting for the owner to decide, with Raj's Reasoning.
        staging = in_project.call(
            "remember",
            title="Staging resets nightly",
            summary="The staging database is wiped every night.",
            type="gotcha",
            body="The staging database is wiped and reseeded every night.",
        )
        challenged = in_project.call("promote", path=staging["path"], level="project")["path"]
        dana_token = owner.call(
            "add_member", member_id="emp-dana", name="Raj Raiser", github="dana"
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
            reasoning="The reset moved to 02:17 UTC when the nightly backup took *midnight*.",
        )
        # Two memories the retire journeys have to themselves, on topics nothing else here touches: retiring
        # one changes nothing another journey reads. Olive's is hers to retire outright; Raj's can only ask
        # him, because retiring another author's memory raises a challenge instead.
        promote_now(
            in_project,
            {
                "title": "Release notes go out on Thursday",
                "summary": "Every release note is published on Thursday morning.",
                "type": "convention",
                "body": "Release notes are published on Thursday morning, after the Wednesday release train "
                "lands.",
            },
        )
        promote_now(
            dana,
            {
                "title": "The API rate limit is 100 a minute",
                "summary": "Billing's public API allows 100 requests a minute per client.",
                "type": "gotcha",
                "body": "Billing's public API allows each client 100 requests a minute; anything above that "
                "gets a 429.",
            },
        )
        # A challenge for the reject journeys, between Olive and a member no other journey signs in as, so
        # it waits on nobody another journey checks has nothing waiting. Both memories set their parts out
        # as a list, which is the shape `whatChanges` can summarise — of prose it has nothing honest to say.
        mira = Session(
            server,
            owner.call("add_member", member_id="emp-mira", name="Mira Maker", github="mira")["personal_token"],
        ).in_project(project, "billing-api")
        stack = promote_keeping_both(
            mira,
            {
                "title": "How Billing is built",
                "summary": "The stack Billing runs on.",
                "type": "decision",
                "body": "- Language: Go\n- Database: Postgres\n- Queue: RabbitMQ",
            },
        )
        challenge(
            in_project,
            {
                "title": "How Billing is built now",
                "summary": "The stack Billing runs on since the queue moved.",
                "type": "decision",
                "body": "- Language: Go\n- Database: Postgres\n- Queue: Kafka",
            },
            stack,
            reasoning="Billing moved its queue to Kafka in March.",
        )
        # A memory Olive imported during onboarding and promoted in Mira's name, for the journey that shows its
        # importer and its source.
        cents = in_project.call(
            "remember",
            title="Money is integer cents",
            summary="Every money amount in billing is stored as integer cents.",
            type="convention",
            body="Every money amount is stored as integer cents, never as a float.",
        )
        imported = in_project.call(
            "promote", path=cents["path"], level="project", author="emp-mira", imported_from="billing-api:CLAUDE.md"
        )
        if imported["status"] == "similar_memories":
            imported = in_project.call(
                "promote",
                path=cents["path"],
                level="project",
                reference=imported["reference"],
                resolutions={one["path"]: "keep_both" for one in imported["similar"]},
            )
        assert imported["status"] == "promoted", imported
        # A challenge for the journey where a project lead decides: in a project Lena leads, against a memory of
        # Wes's, whom no journey signs in as. Olive raises it, so it isn't hers to decide as an admin, and the
        # journeys that check she has nothing waiting still find nothing.
        lena = Session(
            server, owner.call("add_member", member_id="emp-lena", name="Lena Lead", github="lena")["personal_token"]
        )
        reporting = lena.call("create_project", name="Reporting", repository="reporting-api")["project_id"]
        wes = Session(
            server, owner.call("add_member", member_id="emp-wes", name="Wes Writer")["personal_token"]
        ).in_project(reporting, "reporting-api")
        reports = promote_now(
            wes,
            {
                "title": "Reports are built at 06:00",
                "summary": "The daily reports are built at 06:00 UTC.",
                "type": "gotcha",
                "body": "The daily reports are built at 06:00 UTC, before the finance team starts.",
            },
        )
        challenge(
            owner.in_project(reporting, "reporting-api"),
            {
                "title": "Reports are built at 05:00",
                "summary": "The daily reports are built at 05:00 UTC.",
                "type": "gotcha",
                "body": "The daily reports are built at 05:00 UTC since finance moved its start an hour earlier.",
            },
            reports,
            reasoning="Finance starts an hour earlier since June.",
        )
        # A memory of Wes's that no coding agent has used for 61 days, for the journey that shows it possibly outdated.
        # Its last use is moved back below, as the archived card's move is.
        outdated = promote_now(
            wes,
            {
                "title": "Reports render through wkhtmltopdf",
                "summary": "Every report PDF is rendered by wkhtmltopdf.",
                "type": "convention",
                "body": "Render every report PDF from HTML with wkhtmltopdf, on the reporting worker.",
            },
        )
        # Two memories filed under a topic, so the journeys have a topic folder to pin. A topic is a folder
        # inside a type folder, which the type folder itself is not: pinning one puts everything filed under
        # it into every briefing at once.
        for title, body in (
            ("Invoices are immutable", "An invoice is never edited once issued; a correction is a new one."),
            ("Invoices are numbered per year", "Invoice numbers restart at 1 each January, behind the year."),
        ):
            promote_keeping_both(
                in_project,
                {"title": title, "summary": f"{title}.", "type": "convention", "body": body, "topic": "invoicing"},
            )
        # Billing's board, for the board journeys: a card in each column, a memory and a file linked from one, a
        # comment of Raj's, and a card done three weeks ago that has left the board for the archive.
        in_project.call("add_card", title="Retry failed webhooks", priority="high", labels=["webhooks"])
        in_project.call("add_card", title="Split the invoice module", priority="low", labels=["cleanup"])
        in_project.call("add_card", title="Upgrade the queue client", labels=["webhooks"])
        in_project.call("add_card", title="Drop the legacy exporter", labels=["cleanup"])
        in_project.call("add_card", title="Move receipts to the new template")
        in_project.call("claim_card", number=1)
        in_project.call(
            "update_card",
            number=1,
            description="Webhooks that fail are dropped. Retry them with backoff before giving up.",
            memories=[pnpm],
            files=["billing-api:src/webhooks/retry.ts"],
            due_date="2026-09-15",
        )
        dana.call("comment_card", number=1, text="The provider retries three times on its side too.")
        in_project.call(
            "update_card", number=3, column="blocked", blocked_reason="Needs the new retry rules first.", waits_on=1
        )
        in_project.call("update_card", number=4, column="done")
        in_project.call("update_card", number=5, column="done")
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            # Done three weeks before the journeys' clock, which never moves: the only way a card reaches the archive.
            conn.execute(
                "UPDATE cards SET moved_at = moved_at - interval '21 days' WHERE project_id = %s AND number = 5",
                (project,),
            )
            conn.execute(
                "UPDATE memory_uses SET last_used_at = last_used_at - interval '61 days' WHERE path = %s", (outdated,)
            )
        # Billing's active sessions, for the Sessions journey: Raj's, in Claude Code, with an activity it stated and a
        # file it holds, and Olive's, which stated none and so shows her card in Doing. Neither goes idle: the
        # journeys' clock never moves. Reporting has no session, for the page that says so.
        raj = dana.as_agent("claude-code").as_session("raj-backoff")
        raj.call("set_activity", activity="Adding backoff to the webhook retries", session=raj.identifier)
        raj.call("take_lock", path="src/webhooks/backoff.ts", session=raj.identifier)
        olive = in_project.as_agent("codex").as_session("olive-invoices")
        olive.call("take_lock", path="src/invoices/split.ts", session=olive.identifier)
        print(f"console server on {server.url}, fake GitHub on {github.url}, project {project}", flush=True)
        try:
            server.join()
        except KeyboardInterrupt:
            pass
