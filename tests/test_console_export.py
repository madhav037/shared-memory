"""An admin downloads all of the company's data as one archive: the memory folder's git history as a bundle, and JSON of the
members, projects, cards and audit log. Export only reads (ADR-0009), and every one is audited."""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tests.support import NPM, Console, ConsoleClient, Session, add, ask, promote_now, signed_in, signed_in_owner


def opened(archive: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(archive))


def download(client: ConsoleClient) -> zipfile.ZipFile:
    response = client.get("/api/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    return opened(response.content)


def test_an_admin_downloads_the_memory_with_its_history_and_the_companys_records(
    console: Console, signed_out: ConsoleClient, tmp_path: Path
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-export-one", 1601)
    project = owner.call("create_project", name="Billing")["project_id"]
    agent = owner.in_project(project, "billing-api")
    promote_now(agent, NPM)
    agent.call("add_card", title="Retry failed webhooks", labels=["billing"])
    add(signed_out, "emp-2", "Dana Dev", "dana-export-one")

    archive = download(signed_out)

    assert sorted(archive.namelist()) == [
        "audit-log.json",
        "cards.json",
        "departments.json",
        "members.json",
        "memory.bundle",
        "projects.json",
    ]
    members = json.loads(archive.read("members.json"))
    assert [(one["member_id"], one["name"], one["github_login"]) for one in members] == [
        ("E1001", "Olive Owner", "olive-export-one"),
        ("emp-2", "Dana Dev", "dana-export-one"),
    ]
    projects = json.loads(archive.read("projects.json"))
    assert [(one["project_id"], one["name"], one["repositories"]) for one in projects] == [
        (project, "Billing", ["app", "billing-api"])
    ]
    cards = json.loads(archive.read("cards.json"))
    assert [card["title"] for card in cards[project]["columns"]["to_do"]] == ["Retry failed webhooks"]
    assert cards[project]["archive"] == []
    log = json.loads(archive.read("audit-log.json"))
    assert {"signed_in", "project_created", "member_added", "memory_promoted"} <= {event["kind"] for event in log}

    bundle = tmp_path / "memory.bundle"
    bundle.write_bytes(archive.read("memory.bundle"))
    cloned = tmp_path / "cloned"
    subprocess.run(["git", "clone", "-q", str(bundle), str(cloned)], check=True, capture_output=True)  # noqa: S603, S607
    files = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(cloned), "ls-files"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    commits = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(cloned), "log", "--format=%H"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert any(name.endswith(".md") for name in files), "the bundle carries the memory files"
    assert len(commits) >= 2, "and their history, not only the latest version"


def test_a_member_who_is_not_an_admin_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    company, owner_token = console.a_company("olive-export-two")
    Session(console.server, owner_token).call("add_member", member_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--company", company, "--member-id", "emp-2", "--github", "dana-export-two")
    dana = signed_in(console, "dana-export-two", 1602)

    refused = dana.get("/api/export")

    assert refused.status_code == 403
    assert "owner and its admins" in refused.json()["message"]
    assert "zip" not in refused.headers["content-type"]
    dana.close()


def test_the_export_cannot_be_downloaded_without_signing_in(console: Console, signed_out: ConsoleClient) -> None:
    assert signed_out.get("/api/export").status_code == 401


def test_every_export_is_recorded_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-export-three", 1603)

    download(signed_out)
    download(signed_out)

    events: list[dict[str, Any]] = ask(signed_out, "/api/audit", kind="team_exported")["events"]
    assert [(one["kind"], one["actor"]) for one in events] == [("team_exported", "E1001")] * 2


def test_a_refused_export_is_not_recorded(console: Console, signed_out: ConsoleClient) -> None:
    company, owner_token = console.a_company("olive-export-four")
    Session(console.server, owner_token).call("add_member", member_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--company", company, "--member-id", "emp-2", "--github", "dana-export-four")
    dana = signed_in(console, "dana-export-four", 1604)
    dana.get("/api/export")
    dana.close()
    console.github.as_(1605, "olive-export-four")
    signed_out.sign_in()

    assert ask(signed_out, "/api/audit", kind="team_exported")["events"] == []


def test_the_export_tells_an_admin_each_members_verified_email_and_sign_in_methods(
    console: Console, signed_out: ConsoleClient
) -> None:
    console.a_company("olive-export-email")
    console.github.as_(1691, "olive-export-email")
    console.github.has_emails({"email": "olive-export@example.com", "primary": True, "verified": True})
    signed_out.sign_in()

    members = json.loads(download(signed_out).read("members.json"))

    assert [(one["verified_email"], one["sign_in_methods"]) for one in members] == [
        ("olive-export@example.com", ["github"])
    ]


def test_the_memory_bundle_holds_only_the_exporting_companys_memory_and_history(
    console: Console, signed_out: ConsoleClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hardened hosts refuse a bare repository named by -C; the export's copy of the history is one.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.bareRepository")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "explicit")
    other = console.client()
    theirs = signed_in_owner(console, other, "olive-export-theirs", 1611)
    promote_now(theirs.in_project(theirs.call("create_project", name="Theirs")["project_id"], "their-api"), NPM)
    other.close()
    ours = signed_in_owner(console, signed_out, "olive-export-ours", 1613)
    promote_now(ours.in_project(ours.call("create_project", name="Ours")["project_id"], "our-api"), NPM)
    company = signed_out.status()["member"]["company"]

    bundle = tmp_path / "memory.bundle"
    bundle.write_bytes(download(signed_out).read("memory.bundle"))
    cloned = tmp_path / "cloned"
    subprocess.run(["git", "clone", "-q", str(bundle), str(cloned)], check=True, capture_output=True)  # noqa: S603, S607
    every_path = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(cloned), "log", "--all", "--format=", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    refs = subprocess.run(  # noqa: S603, S607
        ["git", "ls-remote", str(bundle)], check=True, capture_output=True, text=True
    ).stdout.splitlines()

    assert [path for path in every_path if path], "the bundle still carries this company's memory and its history"
    assert {path.split("/", 1)[0] for path in every_path if path} == {company}
    assert sorted(line.split()[1] for line in refs) == ["HEAD", "refs/heads/main"], "no other branch or tag"
    assert (cloned / company).is_dir(), "a clone checks out the company's memory"
