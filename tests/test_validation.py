from __future__ import annotations

import subprocess

import pytest

from tests.support import Session, Team


@pytest.fixture
def member(team: Team) -> Session:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    return team.owner().in_project(project, "billing-api")


def remember(session: Session, **overrides: object) -> dict[str, str]:
    arguments: dict[str, object] = {
        "title": "Retries",
        "summary": "Billing retries failed charges.",
        "type": "convention",
        "body": "Retry a failed charge twice.",
    }
    arguments.update(overrides)
    saved: dict[str, str] = session.call("remember", **arguments)
    return saved


def refusal_to_remember(session: Session, **overrides: object) -> str:
    arguments: dict[str, object] = {"title": "Retries", "summary": "s", "type": "convention", "body": "b"}
    arguments.update(overrides)
    return session.refusal("remember", **arguments)


@pytest.mark.parametrize(
    ("secret", "named"),
    [
        ("The deploy key is AKIAIOSFODNN7EXAMPLE for staging.", "AWS access key"),
        ("Use ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ to push.", "GitHub token"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----", "private key"),
        ("Connect with password = hunter2hunter2", "password"),
        ("Database: postgres://billing:s3cretpass@db.internal:5432/billing", "connection string"),
        ("Token: 8fJ2kQ9zX4mB7nL1pR6tW3yV5cH0dG8sA2eK9uI", "high-entropy"),
    ],
)
def test_a_memory_containing_a_secret_is_refused_with_the_reason(member: Session, secret: str, named: str) -> None:
    refusal = refusal_to_remember(member, body=secret)

    assert "secret" in refusal.lower()
    assert named in refusal


def test_ordinary_identifiers_are_not_mistaken_for_secrets(member: Session) -> None:
    body = (
        "Fixed in commit 3f9a1c2b7d4e5f60718293a4b5c6d7e8f9012345. "
        "Request IDs look like 123e4567-e89b-12d3-a456-426614174000. "
        "The password must be rotated every 90 days. Call handleCustomerSubscriptionRenewalRequest."
    )

    assert remember(member, body=body)["path"]


def test_a_memory_over_600_words_is_refused_with_instructions_to_split_it(member: Session) -> None:
    refusal = refusal_to_remember(member, body="word " * 601)

    assert "600 words" in refusal
    assert "topic" in refusal


def test_a_memory_of_exactly_600_words_is_saved(member: Session) -> None:
    assert remember(member, body="word " * 600)["path"]


@pytest.mark.parametrize(
    ("overrides", "complaint"),
    [
        ({"title": "  "}, "title"),
        ({"summary": ""}, "summary"),
        ({"summary": "first line\nsecond line"}, "one line"),
        ({"type": "rule"}, "Unknown memory type"),
        ({"related_files": ["package.json"]}, "repository:path"),
    ],
)
def test_a_memory_with_a_bad_header_is_refused(member: Session, overrides: dict[str, object], complaint: str) -> None:
    assert complaint in refusal_to_remember(member, **overrides)


def test_related_files_are_kept_as_repository_and_path(member: Session) -> None:
    saved = remember(member, related_files=["billing-api:package.json", "billing-web:src/auth.ts"])

    assert member.call("read", path=saved["path"])["related_files"] == [
        "billing-api:package.json",
        "billing-web:src/auth.ts",
    ]


@pytest.mark.parametrize("tool", ["read", "edit_memory", "delete_memory"])
def test_a_path_outside_the_team_folder_is_refused(member: Session, tool: str) -> None:
    arguments: dict[str, object] = {"path": "../other-team/team/conventions/secret.md"}
    if tool == "edit_memory":
        arguments["body"] = "changed"

    assert "not a memory path" in member.refusal(tool, **arguments)


def test_an_author_edits_their_personal_memory(member: Session) -> None:
    saved = remember(member)

    member.call("edit_memory", path=saved["path"], summary="Billing retries twice.", body="Retry twice, then stop.")
    memory = member.call("read", path=saved["path"])

    assert (memory["title"], memory["summary"], memory["body"]) == (
        "Retries",
        "Billing retries twice.",
        "Retry twice, then stop.",
    )


def test_an_edit_is_validated_like_a_save(member: Session) -> None:
    saved = remember(member)

    assert "secret" in member.refusal("edit_memory", path=saved["path"], body="password = hunter2hunter2").lower()


def test_an_edit_cannot_change_a_memory_to_a_type_that_does_not_match_its_folder(member: Session) -> None:
    saved = remember(member)

    assert "match" in member.refusal("edit_memory", path=saved["path"], type="gotcha")


def test_an_author_deletes_their_personal_memory(member: Session) -> None:
    saved = remember(member)

    member.call("delete_memory", path=saved["path"])

    assert "no memory" in member.refusal("read", path=saved["path"])


def test_members_cannot_edit_or_delete_someone_elses_memory(team: Team, member: Session) -> None:
    saved = remember(member)
    added = team.owner().call("add_member", member_id="emp-2", name="Dana Dev")
    other = Session(team.server, added["personal_token"], member.project, "billing-api")

    assert "only edit" in other.refusal("edit_memory", path=saved["path"], body="mine now")
    assert "only delete" in other.refusal("delete_memory", path=saved["path"])


def test_edits_and_deletes_are_committed_and_credited_to_the_member(team: Team, member: Session) -> None:
    saved = remember(member)
    member.call("edit_memory", path=saved["path"], body="Retry twice, then stop.")
    member.call("delete_memory", path=saved["path"])

    log = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "log", "-2", "--format=%an|%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert log == ["Olive Owner|Delete: Retries", "Olive Owner|Edit: Retries"]
