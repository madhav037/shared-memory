"""Commands for the person running the server."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import TextIO

from shared_memory.clock import system_clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Identity

# How long a worker keeps an idle connection open. Longer than a proxy in front keeps its own open to the server
# (Caddy: 2 minutes) or a coding agent waits between calls: uvicorn's 5 seconds made a client, sending on a
# connection just as the server closed it, get no response at all under load (#176).
KEEP_ALIVE_SECONDS = 130


def run(argv: list[str], settings: Settings | None = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="shared-memory")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="Create the team and its owner, and print the owner's personal token.")
    setup.add_argument("--team", required=True, help="Team ID")
    setup.add_argument("--owner-member-id", required=True)
    setup.add_argument("--owner-name", required=True)
    setup.add_argument("--owner-github", help="The owner's GitHub username, so they can sign in to the console.")

    link = commands.add_parser("link-github", help="Link a GitHub account to a member, so they can sign in to the console.")
    link.add_argument("--team", required=True, help="Team ID")
    link.add_argument("--member-id", required=True)
    link.add_argument("--github", required=True, help="Their GitHub username")

    commands.add_parser("reindex", help="Rebuild the search index from the memory files.")

    commands.add_parser("openapi", help="Print the console API's description, which the console builds its types from.")

    serve = commands.add_parser("serve", help="Run the server.")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--workers", type=int, help="How many server processes to run (default: SHARED_MEMORY_WORKERS).")

    args = parser.parse_args(argv)
    settings = settings or Settings.from_env()

    if args.command == "setup":
        db = Database(settings.database_url, settings.statement_timeout_seconds)
        try:
            token = Identity(db, system_clock).setup_team(
                args.team, args.owner_member_id, args.owner_name, args.owner_github
            )
        except Refused as refused:
            print(refused, file=out)
            return 1
        finally:
            db.close()
        print(f"Team: {args.team}", file=out)
        print(f"Owner personal token: {token}", file=out)
        print("Keep this token secret: it is shown only once.", file=out)
        return 0

    if args.command == "reindex":
        from shared_memory.embeddings import CachedQueries, FastEmbedEmbedder
        from shared_memory.index import SearchIndex
        from shared_memory.store import MemoryStore

        db = Database(settings.database_url, settings.statement_timeout_seconds)
        try:
            embedder = CachedQueries(FastEmbedEmbedder(settings.model_cache))
            count = SearchIndex(db, embedder).rebuild(MemoryStore(settings.memory_root))
        finally:
            db.close()
        print(f"Reindexed {count} memories.", file=out)
        return 0

    if args.command == "link-github":
        db = Database(settings.database_url, settings.statement_timeout_seconds)
        try:
            Identity(db, system_clock).link_github(args.team, args.member_id, args.github)
        except Refused as refused:
            print(refused, file=out)
            return 1
        finally:
            db.close()
        print(f"{args.member_id} in team {args.team} signs in to the console as @{args.github.lstrip('@')}.", file=out)
        return 0

    if args.command == "openapi":
        import json

        from shared_memory import console_contract

        print(json.dumps(console_contract.description(), indent=2), file=out)
        return 0

    if args.command == "serve":
        import os

        import uvicorn

        from shared_memory import app

        workers = max(1, args.workers if args.workers is not None else settings.workers)
        # Each worker builds its own app from the environment (`app.worker_app`), so the count that sizes its share of
        # the connections has to be the one that was asked for here.
        os.environ["SHARED_MEMORY_WORKERS"] = str(workers)
        app.setup(settings)
        served = {"host": args.host, "port": args.port, "timeout_keep_alive": KEEP_ALIVE_SECONDS}
        if workers == 1:
            app.show_log()
            uvicorn.run(app.build_app(dataclasses.replace(settings, workers=1), setup=False), **served)
        else:
            uvicorn.run("shared_memory.app:worker_app", factory=True, workers=workers, **served)
        return 0

    return 2


def main() -> None:
    sys.exit(run(sys.argv[1:]))
