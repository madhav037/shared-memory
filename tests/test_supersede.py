from __future__ import annotations

import subprocess

from tests.support import NPM, PNPM, Session, Company, added_context, promote_now, promote_superseding


JSON_LOGS = {
    "title": "Log in JSON",
    "summary": "All services log JSON.",
    "type": "convention",
    "body": "Every service writes structured JSON logs to stdout.",
}
PLAIN_LOGS = {
    "title": "Billing logs plain text",
    "summary": "The billing service logs plain text.",
    "type": "convention",
    "body": "The old billing service writes plain text logs to stdout, not JSON.",
}


def test_superseding_your_own_memory_replaces_it(owner: Session) -> None:
    old = promote_now(owner, NPM)

    result = promote_superseding(owner, PNPM, target=old)
    new = owner.call("read", path=result["path"])
    replaced = owner.call("read", path=old)

    assert result["status"] == "promoted"
    assert (new["status"], new["replaces"]) == ("active", old)
    assert (replaced["status"], replaced["superseded_by"]) == ("superseded", result["path"])


def test_superseding_is_a_single_commit(company: Company, owner: Session) -> None:
    old = promote_now(owner, NPM)

    result = promote_superseding(owner, PNPM, target=old)

    changed = subprocess.run(
        ["git", "-C", str(company.server.settings.memory_root), "show", "--name-only", "--format=%s", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert changed.startswith("Promote: Use pnpm, not npm")
    assert f"{company.code}/{old}" in changed
    assert f"{company.code}/{result['path']}" in changed


def test_a_superseded_memory_leaves_search_and_recall(owner: Session) -> None:
    old = promote_now(owner, NPM)
    promote_superseding(owner, PNPM, target=old)

    found = [result["path"] for result in owner.call("search", query="install dependencies with npm")["results"]]

    assert old not in found
    assert old not in added_context(owner.prompt("which package manager do we use for installs?"))


def test_a_project_memory_contradicting_company_memory_becomes_an_exception(
    company: Company, owner: Session, dana: Session
) -> None:
    company_memory = promote_now(dana, JSON_LOGS, level="company")

    result = promote_superseding(owner, PLAIN_LOGS, target=company_memory)
    exception = owner.call("read", path=result["path"])
    other_project = company.owner().call("create_project", name="Checkout")["project_id"]

    assert (exception["level"], exception["exception_to"]) == ("project", company_memory)
    assert owner.call("read", path=company_memory)["status"] == "active"
    assert company_memory in added_context(company.owner().in_project(other_project).prompt("how should services log?"))


def test_recall_marks_an_exception_so_claude_applies_it_in_that_project(owner: Session, dana: Session) -> None:
    company_memory = promote_now(dana, JSON_LOGS, level="company")
    promote_superseding(owner, PLAIN_LOGS, target=company_memory)

    context = added_context(owner.prompt("how does the billing service write its logs?"))

    assert f"exception to {company_memory}" in context


def test_an_exception_is_told_in_place_of_the_memory_it_overrides(owner: Session, dana: Session) -> None:
    """Asked about the company memory itself, a session where the exception holds is told the exception, labelled,
    and not the company memory it overrides (#634)."""
    company_memory = promote_now(dana, JSON_LOGS, level="company")
    promote_superseding(owner, PLAIN_LOGS, target=company_memory)

    context = added_context(owner.prompt("do all services write structured JSON logs to stdout?"))

    labelled = [line for line in context.splitlines() if line.startswith("[")]
    assert any(f"exception to {company_memory}" in line for line in labelled), context
    assert f"({company_memory})" not in context

