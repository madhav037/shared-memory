"""A memory whose file sits past 260 characters on disk, Windows' limit for an ordinary path (#140).

The memory folder here is deep enough that every memory file under it is past the limit, so each test passes on
Windows only when the server reaches its files by their long form. Elsewhere there is no such limit.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.store import memory_folder
from tests.support import (
    REPO_ROOT,
    Console,
    ConsoleClient,
    FakeGitHub,
    RunningServer,
    Session,
    TestClock,
    ask,
    create,
    fresh_database,
    signed_in_owner,
)

WINDOWS_LIMIT = 260
TOPIC = "How the billing service settles a charge with the card networks"
LONG = {
    "title": "Settlement batches close at midnight in the merchant's own time zone",
    "summary": "A settlement batch closes at the merchant's midnight.",
    "type": "convention",
    "body": "Each merchant's settlement batch closes at midnight in that merchant's own time zone, never in UTC.",
    "topic": TOPIC,
}


def _remove(root: Path) -> None:
    """Remove a folder holding paths past Windows' limit and git's read-only objects."""

    def writable(function: Callable[..., Any], path: str, _: BaseException) -> None:
        os.chmod(path, stat.S_IWRITE)
        function(path)

    shutil.rmtree(memory_folder(root), onexc=writable)


@pytest.fixture(scope="module")
def deep(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Console]:
    """A server with console sign-in whose memory folder is deep enough that a memory under a topic passes the
    limit, and no deeper: git's own files under it stay within the limit."""
    top = tmp_path_factory.mktemp("long")
    memory = top
    while len(str(memory)) < 110:
        memory = memory / "a-memory-folder-kept-deep-inside-other-folders"
    with start_blocking_portal() as portal:
        github = FakeGitHub(portal, Settings("", memory, memory))
        clock = TestClock()
        settings = Settings(
            database_url=fresh_database("shared_memory_long_paths"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=github.url,
            github_api_url=github.url,
        )
        server = RunningServer(build_app(settings, clock=clock), settings, clock, portal)
        try:
            yield Console(server, github, clock)
        finally:
            server.stop()
            github.stop()
            _remove(top)


@pytest.fixture
def browser(deep: Console) -> Iterator[ConsoleClient]:
    client = deep.client()
    try:
        yield client
    finally:
        client.close()


def in_a_project(deep: Console, browser: ConsoleClient, github: str, account: int) -> Session:
    owner = signed_in_owner(deep, browser, github, account)
    return owner.in_project(create(browser, "Billing")["project_id"], "billing-api")


def on_disk(deep: Console, path: str) -> Path:
    """Where a memory's file is on disk, as an ordinary path."""
    root = memory_folder(deep.server.settings.memory_root)
    (team,) = [folder.name for folder in root.iterdir() if folder.joinpath(*path.split("/")).is_file()]
    return deep.server.settings.memory_root.joinpath(team, *path.split("/"))


def test_a_memory_past_the_limit_is_saved_and_read_back(deep: Console, browser: ConsoleClient) -> None:
    member = in_a_project(deep, browser, "olive-long-one", 1401)

    saved = member.call("remember", **LONG)
    file = on_disk(deep, saved["path"])
    read = member.call("read", path=saved["path"])
    listed = member.call("list", folder=saved["path"].rsplit("/", 1)[0])
    found = member.call("search", query="when does a settlement batch close")["results"]

    assert len(str(file)) > WINDOWS_LIMIT
    assert saved["path"].startswith("projects/") and len(saved["path"]) < 200
    assert read["title"] == LONG["title"]
    assert [one["title"] for one in listed["memories"]] == [LONG["title"]]
    assert saved["path"] in [one["path"] for one in found]


def test_a_memory_past_the_limit_is_edited_promoted_retired_and_deleted(deep: Console, browser: ConsoleClient) -> None:
    member = in_a_project(deep, browser, "olive-long-two", 1402)
    personal = member.call("remember", **LONG)["path"]
    other = member.call("remember", **{**LONG, "title": LONG["title"] + ", and reopen at once"})["path"]

    member.call("edit_memory", path=personal, summary="A batch closes at the merchant's own midnight.")
    promoted = member.call("promote", path=personal, level="project")
    retired = member.call("retire", path=promoted["path"])
    deleted = member.call("delete_memory", path=other)

    assert promoted["status"] == "promoted", promoted
    assert len(str(on_disk(deep, promoted["path"]))) > WINDOWS_LIMIT
    assert retired == {"status": "retired", "path": promoted["path"]}
    assert member.call("read", path=promoted["path"])["status"] == "retired"
    assert deleted == {"deleted": other}
    assert "There is no memory" in member.refusal("read", path=other)


def test_the_console_shows_a_memory_past_the_limit_with_its_history(deep: Console, browser: ConsoleClient) -> None:
    member = in_a_project(deep, browser, "olive-long-three", 1403)
    path = member.call("remember", **LONG)["path"]
    member.call("edit_memory", path=path, summary="A batch closes at the merchant's own midnight.")
    folder = path.rsplit("/", 1)[0]

    files = ask(browser, "/api/files", folder=folder)
    shown = ask(browser, "/api/memory", path=path)
    versions = ask(browser, "/api/memory/history", path=path)["versions"]
    first = browser.get(f"/api/memory/version?{urlencode({'path': path, 'commit': versions[-1]['commit']})}").json()

    assert [(one["title"], one["path"]) for one in files["memories"]] == [(LONG["title"], path)]
    assert shown["body"] == LONG["body"]
    assert [version["message"].split(":")[0] for version in versions] == ["Edit", "Remember"]
    assert LONG["summary"] in first["text"]


def test_git_reads_the_history_of_a_memory_folder_past_the_limit(deep: Console, browser: ConsoleClient) -> None:
    member = in_a_project(deep, browser, "olive-long-four", 1404)
    path = member.call("remember", **LONG)["path"]

    printed = subprocess.run(
        ["git", "-C", str(deep.server.settings.memory_root), "show", "--name-only", "--format=%s", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert printed.splitlines()[0] == f"Remember: {LONG['title']}"
    assert any(line.endswith(path) for line in printed.splitlines())
