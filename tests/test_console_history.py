"""A memory's history in the console: every version, what it said, and what changed."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from tests.support import Console, ConsoleClient, Session
from tests.test_console_browsing import ask, signed_in_owner


def changed_twice(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[str, str]:
    """A memory that has been written and then edited twice; returns its project and path."""
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    path: str = in_project.call(
        "remember",
        title="Staging resets nightly",
        summary="Staging is wiped every night.",
        type="gotcha",
        body="The staging database is wiped every night.",
    )["path"]
    in_project.call("edit_memory", path=path, body="The staging database is wiped every night at 02:00 UTC.")
    in_project.call("edit_memory", path=path, body="The staging database is wiped every night at 02:17 UTC.")
    return project, path


def history(client: ConsoleClient, project: str, **asked: Any) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/memory/history", **asked)


def test_a_memory_lists_its_versions_newest_first(console: Console, signed_out: ConsoleClient) -> None:
    project, path = changed_twice(console, signed_out, "olive-history-one", 501)

    versions = history(signed_out, project, path=path)["versions"]

    assert len(versions) == 3
    assert [version["author"] for version in versions] == ["E1001", "E1001", "E1001"]
    assert [version["name"] for version in versions] == ["Olive Owner"] * 3
    assert versions[0]["message"].startswith("Edit")
    assert versions[-1]["message"].startswith("Remember")
    assert versions[0]["at"] >= versions[-1]["at"]


def test_a_version_shows_the_memory_as_it_was_then(console: Console, signed_out: ConsoleClient) -> None:
    project, path = changed_twice(console, signed_out, "olive-history-two", 502)
    versions = history(signed_out, project, path=path)["versions"]

    now = ask(signed_out, f"/api/projects/{project}/memory/version", path=path, commit=versions[0]["commit"])
    first = ask(signed_out, f"/api/projects/{project}/memory/version", path=path, commit=versions[-1]["commit"])

    assert "02:17 UTC" in now["text"]
    assert "02:17" not in first["text"]
    assert "wiped every night" in first["text"]


def test_two_versions_can_be_compared(console: Console, signed_out: ConsoleClient) -> None:
    project, path = changed_twice(console, signed_out, "olive-history-three", 503)
    versions = history(signed_out, project, path=path)["versions"]

    compared = ask(
        signed_out,
        f"/api/projects/{project}/memory/difference",
        path=path,
        before=versions[-1]["commit"],
        after=versions[0]["commit"],
    )

    assert "-The staging database is wiped every night." in compared["difference"]
    assert "+The staging database is wiped every night at 02:17 UTC." in compared["difference"]


def test_promoting_a_memory_shows_in_the_history_of_the_memory_it_became(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-history-four", 504)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    personal = in_project.call(
        "remember", title="Use pnpm, not npm", summary="Billing uses pnpm.", type="convention", body="We use pnpm."
    )["path"]
    promoted = in_project.call("promote", path=personal, level="project")["path"]

    versions = history(signed_out, project, path=promoted)["versions"]

    assert [version["message"].split(":")[0] for version in versions] == ["Promote"]


def test_history_is_refused_for_a_memory_that_is_not_there(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-history-five", 505)
    project = owner.call("create_project", name="Billing")["project_id"]

    missing = signed_out.get(
        f"/api/projects/{project}/memory/history?{urlencode({'path': f'projects/{project}/shared/gotchas/nothing.md'})}"
    )
    outside = signed_out.get(
        f"/api/projects/{project}/memory/history?{urlencode({'path': '../../etc/passwd'})}"
    )

    assert missing.status_code == 403
    assert outside.status_code == 403


def test_a_made_up_version_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    project, path = changed_twice(console, signed_out, "olive-history-six", 506)

    refused = signed_out.get(
        f"/api/projects/{project}/memory/version?{urlencode({'path': path, 'commit': 'not-a-commit'})}"
    )

    assert refused.status_code == 403
    assert "not a version" in refused.json()["message"]
