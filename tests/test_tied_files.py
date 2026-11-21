"""A memory's tied files: the files, written repository:path, that it is about."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from tests.support import Console, ConsoleClient, RunningServer, Session, Company, add, ask, create, signed_in_owner

KNOWN_ISSUE = {
    "title": "Uploads flake on staging",
    "summary": "Large uploads to staging time out now and then.",
    "body": "Uploads over 50 MB to staging time out about one time in five.\n\nWorkaround: retry the upload.",
}


@pytest.fixture
def member(company: Company) -> Session:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    return company.owner().in_project(project, "billing-api")


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


def file_of(server: RunningServer, company_code: str, path: str) -> Path:
    return Path(server.settings.memory_root, company_code, *PurePosixPath(path).parts)


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
    company_code, owner_token = console.a_company("olive-tied-old")
    console.github.as_(371, "olive-tied-old")
    signed_out.sign_in()
    owner = Session(console.server, owner_token)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    path = remember(in_project, tied_files=["billing-api:src/tax.ts", "billing-web:src/invoice.ts"])
    file = file_of(console.server, company_code, path)

    header_says_related_files(file)

    assert "related_files:" in file.read_text(encoding="utf-8")
    assert in_project.call("read", path=path)["tied_files"] == ["billing-api:src/tax.ts", "billing-web:src/invoice.ts"]
    assert ask(signed_out, "/api/memory", path=path)["tied_files"] == [
        "billing-api:src/tax.ts",
        "billing-web:src/invoice.ts",
    ]


def test_an_edited_memory_writes_tied_files_not_related_files(company: Company, member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])
    file = file_of(company.server, company.code, path)
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


# Tied files as folder globs, the tied-file index, and `tied_memories` (#548).


def tied(session: Session, file: str) -> list[str]:
    """The paths of the memories `tied_memories` gives a session for a file."""
    return [each["path"] for each in session.call("tied_memories", file=file)["memories"]]


def promoted(session: Session, level: str = "project", **overrides: object) -> str:
    """A memory remembered with these details and promoted, keeping both of anything similar it is shown."""
    personal = remember(session, **overrides)
    result = session.call("promote", path=personal, level=level)
    if result["status"] == "similar_memories":
        result = session.call(
            "promote",
            path=personal,
            level=level,
            reference=result["reference"],
            resolutions={similar["path"]: "keep_both" for similar in result["similar"]},
        )
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def test_remember_takes_a_folder_glob_as_a_tied_file(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax/**"])
    refusal = member.refusal(
        "remember", title="Tax", summary="s", type="gotcha", body="b", tied_files=["billing-api:src/{tax,fees}/**"]
    )

    assert member.call("read", path=path)["tied_files"] == ["billing-api:src/tax/**"]
    assert "Tied file 'billing-api:src/{tax,fees}/**' isn't a usable glob" in refusal
    assert "`!`, `[...]` and `{...}` are not read" in refusal, "the never-lock pattern rules' reason"


def test_tied_memories_finds_a_memory_tied_to_the_file_exactly(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])

    found = member.call("tied_memories", file="billing-api:src/tax.ts")

    assert [each["path"] for each in found["memories"]] == [path]
    shown = found["memories"][0]
    assert (shown["level"], shown["tied_file"]) == ("personal", "billing-api:src/tax.ts")
    assert "Round the tax on each line" in shown["body"]
    assert tied(member, "billing-api:src/fees.ts") == []


def test_tied_memories_finds_a_memory_tied_by_a_folder_glob(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax/**"])

    assert tied(member, "billing-api:src/tax/rates/vat.ts") == [path]
    assert tied(member, "billing-api:src/tax.ts") == []
    assert tied(member, "billing-api:lib/src/tax/vat.ts") == [], "a glob with a slash is matched from the root"


def test_a_tied_file_without_glob_characters_ties_only_that_file_from_the_root(member: Session) -> None:
    at_the_root = remember(member, tied_files=["billing-api:package.json"])
    nested = remember(member, title="Tax rounding in one module", tied_files=["billing-api:src/tax/rounding.ts"])

    assert tied(member, "billing-api:package.json") == [at_the_root]
    assert tied(member, "billing-api:web/package.json") == [], "a plain path without a slash is not a file's name"
    assert tied(member, "billing-api:src/tax/rounding.ts") == [nested]
    assert tied(member, "billing-api:lib/src/tax/rounding.ts") == []


def test_a_tied_glob_follows_the_never_lock_pattern_rules(member: Session) -> None:
    by_name = remember(member, tied_files=["billing-api:*.json"])
    in_one_folder = remember(member, title="Tax modules", tied_files=["billing-api:src/tax/*.ts"])

    assert tied(member, "billing-api:web/package.json") == [by_name], "a glob without a slash matches a name anywhere"
    assert tied(member, "billing-api:src/tax/vat.ts") == [in_one_folder]
    assert tied(member, "billing-api:src/tax/rates/vat.ts") == [], "`*` stays within one folder"


def test_tied_memories_ignores_a_tie_to_the_same_path_in_another_repository(member: Session) -> None:
    remember(member, tied_files=["billing-web:src/tax.ts"])

    assert tied(member, "billing-api:src/tax.ts") == []


def test_tied_memories_never_gives_another_members_personal_memory(owner: Session, dana: Session) -> None:
    owners = remember(owner, tied_files=["billing-api:src/tax.ts"])

    assert tied(owner, "billing-api:src/tax.ts") == [owners]
    assert tied(dana, "billing-api:src/tax.ts") == []


def test_tied_memories_never_gives_memory_of_a_restricted_project_the_caller_cannot_reach(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-tied-vault", 1801)
    billing = create(signed_out, "Billing")["project_id"]
    vault = create(signed_out, "Vault")["project_id"]
    payments = create(signed_out, "Payments")["project_id"]
    restricting = signed_out.post_json(f"/api/projects/{vault}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev", "dana-tied-vault")["personal_token"])
    promoted(owner.in_project(vault, "vault-api"), title="Vault keys rotate", tied_files=["shared-lib:src/keys.ts"])
    readable = promoted(
        owner.in_project(payments, "payments-api"), title="Payment keys rotate", tied_files=["shared-lib:src/keys.ts"]
    )

    in_billing = promoted(
        owner.in_project(billing, "billing-api"), title="Billing keys rotate", tied_files=["shared-lib:src/keys.ts"]
    )

    found = tied(dana.in_project(billing, "billing-api"), "shared-lib:src/keys.ts")

    assert found == [in_billing], "recall's reach: this project's memory, never another project's"
    assert tied(dana.in_project(payments, "payments-api"), "shared-lib:src/keys.ts") == [readable]


def test_tied_memories_gives_own_personal_project_and_company_memory(owner: Session, dana: Session) -> None:
    file = ["billing-api:src/tax.ts"]
    in_company = promoted(owner, "company", title="Tax is per line everywhere", tied_files=file)
    in_project = promoted(owner, "project", title="Billing rounds tax per line", tied_files=file)
    mine = remember(dana, title="My note on tax rounding", tied_files=file)

    found = dana.call("tied_memories", file="billing-api:src/tax.ts")["memories"]

    assert sorted((each["path"], each["level"]) for each in found) == sorted(
        [(in_company, "company"), (in_project, "project"), (mine, "personal")]
    )


def test_a_tied_memory_in_doubt_is_marked_in_doubt(owner: Session, dana: Session) -> None:
    doubted = promoted(owner, title="Tax rounds down", tied_files=["billing-api:src/tax.ts"])
    sound = promoted(owner, title="Tax is per line", tied_files=["billing-api:src/tax/**", "billing-api:src/tax.ts"])
    dana.call("challenge", path=doubted, reason="misled")

    found = {each["path"]: each for each in dana.call("tied_memories", file="billing-api:src/tax.ts")["memories"]}

    assert found[doubted]["in_doubt"] == "In doubt: 1 says it misled them"
    assert "in_doubt" not in found[sound]


def test_a_retired_or_superseded_memory_is_no_longer_tied(owner: Session) -> None:
    body = "Round the tax on each line before adding them up, then round the total."
    retired = promoted(owner, title="Tax rounding is per line", body=body, tied_files=["billing-api:src/tax.ts"])
    old = promoted(owner, title="Fees round per line", body=body, tied_files=["billing-api:src/fees.ts"])
    personal = remember(owner, title="Fees round per line, always", body=body, tied_files=["billing-api:src/fees.ts"])
    first = owner.call("promote", path=personal, level="project")
    assert first["status"] == "similar_memories", first
    newer = owner.call(
        "promote",
        path=personal,
        level="project",
        reference=first["reference"],
        resolutions={each["path"]: "supersede" if each["path"] == old else "keep_both" for each in first["similar"]},
    )
    assert newer["status"] == "promoted", newer

    owner.call("retire", path=retired)

    assert tied(owner, "billing-api:src/tax.ts") == []
    assert tied(owner, "billing-api:src/fees.ts") == [newer["path"]]


def test_a_deleted_memory_is_no_longer_tied(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])

    member.call("delete_memory", path=path)

    assert tied(member, "billing-api:src/tax.ts") == []


def test_a_promoted_memory_stays_tied_at_its_new_path(member: Session) -> None:
    personal = remember(member, tied_files=["billing-api:src/tax/**"])
    result = member.call("promote", path=personal, level="project")
    if result["status"] == "similar_memories":
        keep_both = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = member.call(
            "promote", path=personal, level="project", reference=result["reference"], resolutions=keep_both
        )
    assert result["status"] == "promoted", result

    assert tied(member, "billing-api:src/tax/vat.ts") == [result["path"]]


def test_an_edit_that_changes_tied_files_moves_the_tie(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])

    member.call("edit_memory", path=path, tied_files=["billing-api:src/tax/rounding.ts"])

    assert tied(member, "billing-api:src/tax.ts") == []
    assert tied(member, "billing-api:src/tax/rounding.ts") == [path]


def test_reindex_rebuilds_the_tied_file_index_from_memory_on_disk(company: Company, member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])
    file = file_of(company.server, company.code, path)
    # Written on disk the way memory was before related files became tied files, and tied somewhere new.
    header_says_related_files(file)
    file.write_text(file.read_text(encoding="utf-8").replace("src/tax.ts", "src/tax/**"), encoding="utf-8")

    company.server.run_cli("reindex")

    assert "related_files:\n- billing-api:src/tax/**" in file.read_text(encoding="utf-8")
    assert tied(member, "billing-api:src/tax.ts") == []
    assert tied(member, "billing-api:src/tax/vat.ts") == [path]


# `tie`: a session replaces a memory's tied files (#550).


def test_tie_replaces_a_memorys_tied_files(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])

    tied_now = member.call("tie", path=path, tied_files=["billing-api:src/tax/**"])

    assert tied_now["tied_files"] == ["billing-api:src/tax/**"]
    assert member.call("read", path=path)["tied_files"] == ["billing-api:src/tax/**"]
    assert tied(member, "billing-api:src/tax.ts") == [], "the old file no longer brings it up"
    assert tied(member, "billing-api:src/tax/rates/vat.ts") == [path], "the new glob does"


def test_tie_is_in_the_memorys_history(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-tie-history", 1850)
    in_project = owner.in_project(owner.call("create_project", name="Billing")["project_id"], "billing-api")
    path = remember(in_project, tied_files=["billing-api:src/tax.ts"])

    in_project.call("tie", path=path, tied_files=["billing-api:src/tax/**"])

    versions = ask(signed_out, "/api/memory/history", path=path)["versions"]
    assert [version["message"].split(":")[0] for version in versions] == ["Tie", "Remember"]
    assert versions[0]["author"] == versions[1]["author"], "credited to the member who tied it"
    retied = ask(signed_out, "/api/memory/version", path=path, commit=versions[0]["commit"])["text"]
    assert "billing-api:src/tax/**" in retied


def test_tie_on_another_members_memory_is_refused(owner: Session, dana: Session) -> None:
    owners = remember(owner, tied_files=["billing-api:src/tax.ts"])

    refusal = dana.refusal("tie", path=owners, tied_files=["billing-api:src/tax/**"])

    assert "You can only tie your own personal memory" in refusal
    assert owner.call("read", path=owners)["tied_files"] == ["billing-api:src/tax.ts"]
    assert tied(owner, "billing-api:src/tax/vat.ts") == []


def test_tie_on_project_or_company_memory_is_refused_until_it_is_superseded(owner: Session) -> None:
    in_project = promoted(owner, "project", title="Billing rounds tax per line", tied_files=["billing-api:src/tax.ts"])
    in_company = promoted(owner, "company", title="Tax is per line everywhere", tied_files=["billing-api:src/tax.ts"])

    refusals = [owner.refusal("tie", path=path, tied_files=["billing-api:src/tax/**"]) for path in (in_project, in_company)]

    assert all("You can only tie your own personal memory" in refusal for refusal in refusals), refusals
    assert all("promoting a memory that supersedes it" in refusal for refusal in refusals), refusals
    assert tied(owner, "billing-api:src/tax/vat.ts") == []


def test_tie_with_an_unusable_glob_is_refused(member: Session) -> None:
    path = remember(member, tied_files=["billing-api:src/tax.ts"])

    refusal = member.refusal("tie", path=path, tied_files=["billing-api:src/tax/**", "billing-api:src/{tax,fees}/**"])

    assert "Tied file 'billing-api:src/{tax,fees}/**' isn't a usable glob" in refusal
    assert member.call("read", path=path)["tied_files"] == ["billing-api:src/tax.ts"]
    assert tied(member, "billing-api:src/tax.ts") == [path]
