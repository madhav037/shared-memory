"""Commands for the person running the server."""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from shared_memory.clock import system_clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Identity


def run(argv: list[str], settings: Settings | None = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="shared-memory")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="Create the team and its owner, and print the owner's personal token.")
    setup.add_argument("--team", required=True, help="Team ID")
    setup.add_argument("--owner-employee-id", required=True)
    setup.add_argument("--owner-name", required=True)
    setup.add_argument("--owner-github", help="The owner's GitHub username, so they can sign in to the console.")

    link = commands.add_parser("link-github", help="Link a GitHub account to a member, so they can sign in to the console.")
    link.add_argument("--team", required=True, help="Team ID")
    link.add_argument("--employee-id", required=True)
    link.add_argument("--github", required=True, help="Their GitHub username")

    commands.add_parser("reindex", help="Rebuild the search index from the memory files.")

    commands.add_parser("openapi", help="Print the console API's description, which the console builds its types from.")

    serve = commands.add_parser("serve", help="Run the server.")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    settings = settings or Settings.from_env()

    if args.command == "setup":
        db = Database(settings.database_url)
        try:
            token = Identity(db, system_clock).setup_team(
                args.team, args.owner_employee_id, args.owner_name, args.owner_github
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
        from shared_memory.embeddings import FastEmbedEmbedder
        from shared_memory.index import SearchIndex
        from shared_memory.store import MemoryStore

        db = Database(settings.database_url)
        try:
            count = SearchIndex(db, FastEmbedEmbedder(settings.model_cache)).rebuild(MemoryStore(settings.memory_root))
        finally:
            db.close()
        print(f"Reindexed {count} memories.", file=out)
        return 0

    if args.command == "link-github":
        db = Database(settings.database_url)
        try:
            Identity(db, system_clock).link_github(args.team, args.employee_id, args.github)
        except Refused as refused:
            print(refused, file=out)
            return 1
        finally:
            db.close()
        print(f"{args.employee_id} in team {args.team} signs in to the console as @{args.github.lstrip('@')}.", file=out)
        return 0

    if args.command == "openapi":
        import json

        from shared_memory import console_api

        print(json.dumps(console_api.description(), indent=2), file=out)
        return 0

    if args.command == "serve":
        import uvicorn

        from shared_memory.app import build_app

        uvicorn.run(build_app(settings), host=args.host, port=args.port)
        return 0

    return 2


def main() -> None:
    sys.exit(run(sys.argv[1:]))
