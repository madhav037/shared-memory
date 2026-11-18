"""A memory's tied files: the files, written repository:path, that it is about."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from tests.support import Console, ConsoleClient, RunningServer, Session, Team, ask

KNOWN_ISSUE = {
    "title": "Uploads flake on staging",
    "summary": "Large uploads to staging time out now and then.",
    "body": "Uploads over 50 MB to staging time out about one time in five.\n\nWorkaround: retry the upload.",
}


@pytest.fixture
def member(team: Team) -> Session:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    return team.owner().in_project(project, "billing-api")


def remember(session: Session, **overrides: object) -> str:
    arguments: dict[str, object] = {
        "title": "Tax rounding",
        "summary": "Tax is rounded per line, not per invoice.",
        "type": "gotcha",
        "body": "Round the tax on each line before adding them up.",
    }
    arguments.update(overrides)
    path: str = session.call("remember", **arguments)["path"]
    return path


def file_of(server: RunningServer, team_code: str, path: str) -> Path:
    return Path(server.settings.memory_root, team_code, *PurePosixPath(path).parts)


def header_says_related_files(file: Path) -> None:
    """Rewrite a memory's header the way it was written before related files became tied files."""
    text = file.read_text(encoding="utf-8")
    assert "tied_files:" in text
    with file.open("r+", encoding="utf-8", newline="\n") as edited:
        edited.write(text.replace("tied_files:", "related_files:"))
        edited.truncate()


def test_remember_takes_tied_files_written_as_repository_path(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])

    assert member.call("read", path=path)["tied_files"] == ["billing-api:src/tax.ts"]


def test_a_memory_saved_with_related_files_is_read_with_tied_files(console: Console, signed_out: ConsoleClient) -> None:
    team_code, owner_token = console.a_team("olive-tied-old")
    console.github.as_(371, "olive-tied-old")
    signed_out.sign_in()
    owner = Session(console.server, owner_token)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    path = remember(in_project, tied_files=["billing-api:src/tax.ts", "billing-web:src/invoice.ts"])
    file = file_of(console.server, team_code, path)

    header_says_related_files(file)

    assert "related_files:" in file.read_text(encoding="utf-8")
    assert in_project.call("read", path=path)["tied_files"] == ["billing-api:src/tax.ts", "billing-web:src/invoice.ts"]
    assert ask(signed_out, "/api/memory", path=path)["tied_files"] == [
        "billing-api:src/tax.ts",
        "billing-web:src/invoice.ts",
    ]


def test_an_edited_memory_writes_tied_files_not_related_files(team: Team, member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])
    file = file_of(team.server, team.code, path)
    header_says_related_files(file)

    member.call("edit_memory", path=path, summary="Tax is rounded per line, always.")

    header = file.read_text(encoding="utf-8").split("---")[1]
    assert "tied_files:\n- billing-api:src/tax.ts" in header
    assert "related_files" not in header


def test_edit_memory_replaces_tied_files(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])

    member.call("edit_memory", path=path, tied_files=["billing-api:src/tax/rounding.ts"])

    assert member.call("read", path=path)["tied_files"] == ["billing-api:src/tax/rounding.ts"]


def test_save_known_issue_takes_tied_files(member: Session) -> None:
    result = member.call("save_known_issue", **KNOWN_ISSUE, tied_files=["billing-api:src/upload.ts"])
    if result["status"] == "similar_memories":
        keep_all = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = member.call(
            "save_known_issue",
            **KNOWN_ISSUE,
            tied_files=["billing-api:src/upload.ts"],
            reference=result["reference"],
            resolutions=keep_all,
        )

    assert result["status"] == "saved", result
    assert member.call("read", path=result["path"])["tied_files"] == ["billing-api:src/upload.ts"]


def test_a_tied_file_not_written_as_repository_path_is_refused(member: Session) -> None:
    refusal = member.refusal("remember", title="Tax", summary="s", type="gotcha", body="b", tied_files=["src/tax.ts"])

    assert "Tied file 'src/tax.ts' must be written as repository:path" in refusal
