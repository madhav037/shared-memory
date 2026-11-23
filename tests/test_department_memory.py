"""Department memory end to end (#631, ADR-0032, ADR-0033).

Level gains `department`, between project and company. A department lead's session promotes a memory there, with the
usual similar-memory check, and can pin it. Sessions in the department's projects are briefed with its pins and
recall and search it; a session in any other project never sees it, and a project in no department is briefed exactly
as before. The console shows department memory in its tree with its level, and filters search by it. Removing a
department retires its memory and keeps its history; the company's export carries departments and their memory.

Sessions are driven over HTTP and the console through its JSON API, both on the console's server.
"""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from tests.support import (
    Console,
    ConsoleClient,
    Session,
    added_context,
    ask,
    create,
    signed_in_owner,
)

REVIEWS = {
    "title": "Two reviewers on every change",
    "summary": "Every pull request in payments needs two approving reviewers.",
    "type": "convention",
    "body": "Every pull request needs two approving reviewers before it merges. Rubber stamps are not reviews.",
}
GATEWAY = {
    "title": "Gateway timeouts",
    "summary": "The payment gateway times out after 30 seconds.",
    "type": "gotcha",
    "body": "When the payment gateway is slow the client raises ERR_TIMEOUT after 30 seconds.",
}


def department(client: ConsoleClient, name: str, *projects: str, lead: str | None = "E1001") -> str:
    """A department made through the console, with a lead and projects in it; returns its department ID."""
    made = client.post_json("/api/departments", {"name": name})
    assert made.status_code == 200, made.text
    department_id: str = next(one for one in made.json()["departments"] if one["name"] == name)["department_id"]
    if lead is not None:
        appointed = client.post_json(f"/api/departments/{department_id}/leads", {"member_id": lead})
        assert appointed.status_code == 200, appointed.text
    for project in projects:
        moved = client.post_json(f"/api/departments/{department_id}/projects", {"project_id": project})
        assert moved.status_code == 200, moved.text
    return department_id


def promoted(session: Session, memory: dict[str, str], level: str) -> str:
    """Promote a fresh memory, keeping both of anything similar it is shown."""
    personal = session.call("remember", **memory)["path"]
    first = session.call("promote", path=personal, level=level)
    if first["status"] == "similar_memories":
        first = session.call(
            "promote",
            path=personal,
            level=level,
            reference=first["reference"],
            resolutions={one["path"]: "keep_both" for one in first["similar"]},
        )
    assert first["status"] == "promoted", first
    path: str = first["path"]
    return path


def test_a_department_lead_promotes_into_department_memory_readable_at_its_department_location(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-memory-one", 1901)
    billing = create(signed_out, "Billing")["project_id"]
    payments = department(signed_out, "Payments", billing)
    session = owner.in_project(billing)

    path = promoted(session, REVIEWS, "department")

    assert path.startswith(f"departments/{payments}/conventions/")
    read = session.call("read", path=path)
    assert read["level"] == "department"
    assert read["status"] == "active"
    assert read["promoted_by"] is None
    assert ask(signed_out, "/api/memory", path=path)["level"] == "department"


def test_promoting_into_department_memory_from_a_project_in_no_department_is_refused(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-memory-three", 1903)
    ledger = create(signed_out, "Ledger")["project_id"]
    session = owner.in_project(ledger)
    personal = session.call("remember", **REVIEWS)["path"]

    refused = session.refusal("promote", path=personal, level="department")

    assert "no department" in refused
    assert session.call("read", path=personal)["level"] == "personal"


def test_department_pins_brief_only_the_departments_projects_and_a_project_in_none_is_briefed_as_today(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-memory-four", 1904)
    billing = create(signed_out, "Billing")["project_id"]
    invoices = create(signed_out, "Invoices")["project_id"]
    ledger = create(signed_out, "Ledger")["project_id"]
    platform = create(signed_out, "Platform")["project_id"]
    department(signed_out, "Payments", billing, invoices)
    department(signed_out, "Infrastructure", platform)
    company_path = promoted(owner.in_project(ledger), GATEWAY, "company")
    owner.in_project(ledger).call("pin", path=company_path)
    owner.in_project(ledger).start()  # anything said only on a first session is said now
    before = added_context(owner.in_project(ledger).start())

    path = promoted(owner.in_project(billing), REVIEWS, "department")
    owner.in_project(billing).call("pin", path=path)

    in_billing = added_context(owner.in_project(billing).start())
    in_invoices = added_context(owner.in_project(invoices).start())
    assert f"[department memory] Two reviewers on every change ({path})" in in_billing
    assert f"[department memory] Two reviewers on every change ({path})" in in_invoices
    assert f"[company memory] Gateway timeouts ({company_path})" in in_invoices
    assert "Two reviewers" not in added_context(owner.in_project(platform).start())
    assert added_context(owner.in_project(ledger).start()) == before


def test_recall_and_search_find_department_memory_only_in_its_projects(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-memory-five", 1905)
    billing = create(signed_out, "Billing")["project_id"]
    invoices = create(signed_out, "Invoices")["project_id"]
    ledger = create(signed_out, "Ledger")["project_id"]
    department(signed_out, "Payments", billing, invoices)
    path = promoted(owner.in_project(billing), REVIEWS, "department")

    found = owner.in_project(invoices).call("search", query="how many reviewers approve a pull request")
    filtered = owner.in_project(invoices).call("search", query="reviewers", level="department")
    elsewhere = owner.in_project(ledger).call("search", query="how many reviewers approve a pull request")
    recalled = added_context(owner.in_project(invoices).prompt("How many reviewers must approve a pull request?"))
    not_recalled = added_context(owner.in_project(ledger).prompt("How many reviewers must approve a pull request?"))

    hit = next(one for one in found["results"] if one["path"] == path)
    assert hit["level"] == "department"
    assert hit["label"] == "department memory"
    assert [one["path"] for one in filtered["results"]] == [path]
    assert path not in [one["path"] for one in elsewhere["results"]]
    assert path in recalled
    assert path not in not_recalled


def test_the_console_shows_department_memory_in_the_tree_with_its_level_and_filters_search_by_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-memory-six", 1906)
    billing = create(signed_out, "Billing")["project_id"]
    payments = department(signed_out, "Payments", billing)
    path = promoted(owner.in_project(billing), REVIEWS, "department")
    company_path = promoted(owner.in_project(billing), GATEWAY, "company")

    top = ask(signed_out, "/api/files", folder="")
    inside = ask(signed_out, "/api/files", folder=f"departments/{payments}", deep="1")
    by_department = ask(signed_out, "/api/search", query="reviewers gateway", level="department")
    by_company = ask(signed_out, "/api/search", query="reviewers gateway", level="company")

    shown = next(one for one in top["folders"] if one["path"] == f"departments/{payments}")
    assert shown["kind"] == "department"
    assert shown["name"] == "Payments"
    assert shown["memories"] == 1
    memories = [one for section in inside["inside"] for one in section["memories"]]
    assert [(one["path"], one["level"]) for one in memories] == [(path, "department")]
    assert [hit["path"] for hit in by_department["results"]] == [path]
    assert [hit["path"] for hit in by_company["results"]] == [company_path]


def test_removing_a_department_retires_its_memory_and_keeps_its_history(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-memory-seven", 1907)
    billing = create(signed_out, "Billing")["project_id"]
    payments = department(signed_out, "Payments", billing)
    path = promoted(owner.in_project(billing), REVIEWS, "department")
    session = owner.in_project(billing)
    versions = len(ask(signed_out, "/api/memory/history", path=path)["versions"])

    removed = signed_out.post_json(f"/api/departments/{payments}/remove", {})

    assert removed.status_code == 200, removed.text
    assert session.call("read", path=path)["status"] == "retired"
    assert len(ask(signed_out, "/api/memory/history", path=path)["versions"]) == versions + 1
    assert path not in [one["path"] for one in session.call("search", query="reviewers")["results"]]
    retired = [
        event
        for event in ask(signed_out, "/api/audit")["events"]
        if event["kind"] == "memory_retired" and event["target"] == path
    ]
    assert len(retired) == 1


def test_the_export_carries_departments_and_department_memory(
    console: Console, signed_out: ConsoleClient, tmp_path: Path
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-dept-memory-eight", 1908)
    billing = create(signed_out, "Billing")["project_id"]
    payments = department(signed_out, "Payments", billing)
    path = promoted(owner.in_project(billing), REVIEWS, "department")

    response = signed_out.post("/api/export")

    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    exported: list[dict[str, Any]] = json.loads(archive.read("departments.json"))
    assert [(one["department_id"], one["name"]) for one in exported] == [(payments, "Payments")]
    assert exported[0]["projects"] == [billing]
    assert exported[0]["leads"] == ["E1001"]
    bundle = tmp_path / "memory.bundle"
    bundle.write_bytes(archive.read("memory.bundle"))
    cloned = tmp_path / "cloned"
    subprocess.run(["git", "clone", "-q", str(bundle), str(cloned)], check=True, capture_output=True)  # noqa: S603, S607
    assert any(str(found).replace("\\", "/").endswith(path) for found in cloned.rglob("*.md"))
