"""Browsing memory as files: the whole folder structure a member can reach, and any memory read by its path."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from tests.support import Console, ConsoleClient
from tests.test_console_browsing import signed_in_owner
from tests.test_console_members import add
from tests.test_console_projects import create
from tests.test_restricted_projects import signed_in


def files(client: ConsoleClient, folder: str = "") -> dict[str, Any]:
    response = client.get(f"/api/files?{urlencode({'folder': folder})}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def memory(client: ConsoleClient, path: str) -> dict[str, Any]:
    response = client.get(f"/api/memory?{urlencode({'path': path})}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def a_team_with_memory(console: Console, client: ConsoleClient, github: str, account: int) -> dict[str, Any]:
    """Two projects, one with project, personal and team memory in it."""
    owner = signed_in_owner(console, client, github, account)
    billing = create(client, "Billing")["project_id"]
    payments = create(client, "Payments")["project_id"]
    in_billing = owner.in_project(billing, "billing-api")
    pnpm = in_billing.call(
        "promote",
        path=in_billing.call(
            "remember", title="Use pnpm, not npm", summary="Billing uses pnpm.", type="convention", body="We use pnpm."
        )["path"],
        level="project",
    )["path"]
    logging = in_billing.call(
        "promote",
        path=in_billing.call(
            "remember",
            title="Every service logs JSON",
            summary="One JSON object per line.",
            type="convention",
            body="Every service logs one JSON object per line.",
        )["path"],
        level="team",
    )["path"]
    note = in_billing.call(
        "remember", title="My staging trick", summary="Mine.", type="gotcha", body="I reset staging by hand."
    )["path"]
    return {"owner": owner, "billing": billing, "payments": payments, "pnpm": pnpm, "logging": logging, "note": note}


def test_the_top_holds_team_memory_and_every_project_with_what_each_holds(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-one", 1201)

    top = files(signed_out)

    assert top["folder"] == ""
    assert [(one["name"], one["kind"], one["memories"]) for one in top["folders"]] == [
        ("Team memory", "team", 1),
        ("Billing", "project", 2),
        ("Payments", "project", 0),
    ]
    assert top["folders"][1]["path"] == f"projects/{it['billing']}"
    assert top["folders"][1]["changed"] is not None
    assert top["memories"] == []


def test_folders_are_named_the_way_members_say_them(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-two", 1202)

    project = files(signed_out, f"projects/{it['billing']}")
    people = files(signed_out, f"projects/{it['billing']}/people")
    conventions = files(signed_out, f"projects/{it['billing']}/shared/conventions")

    assert [(one["name"], one["kind"]) for one in project["folders"]] == [
        ("Project memory", "shared"),
        ("Personal memory", "people"),
    ]
    assert [(one["name"], one["kind"]) for one in people["folders"]] == [("Olive Owner", "member")]
    assert conventions["name"] == "Conventions"
    assert [crumb["name"] for crumb in conventions["trail"]] == ["Billing", "Project memory"]
    assert [(one["title"], one["level"], one["status"], one["author_name"]) for one in conventions["memories"]] == [
        ("Use pnpm, not npm", "project", "active", "Olive Owner")
    ]


def test_any_memory_reads_by_its_path_with_its_file_as_claude_reads_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-three", 1203)

    team = memory(signed_out, it["logging"])
    personal = memory(signed_out, it["note"])

    assert team["level"] == "team"
    assert team["body"] == "Every service logs one JSON object per line."
    assert team["source"].startswith("---\ntitle: Every service logs JSON\n")
    assert team["source"].rstrip().endswith("Every service logs one JSON object per line.")
    assert personal["level"] == "personal"
    assert personal["author_name"] == "Olive Owner"


def test_retired_memory_keeps_its_place_and_says_so(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-four", 1204)

    retired = signed_out.post_json("/api/memory/retire", {"path": it["pnpm"]})
    conventions = files(signed_out, f"projects/{it['billing']}/shared/conventions")

    assert retired.json() == {"status": "retired", "path": it["pnpm"], "challenge_id": None}
    assert [(one["title"], one["status"]) for one in conventions["memories"]] == [("Use pnpm, not npm", "retired")]


def test_a_memory_is_pinned_and_unpinned_by_its_path(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-five", 1205)

    pinned = signed_out.post_json("/api/memory/pin", {"path": it["logging"]})
    listed = files(signed_out, "team/conventions")["memories"]
    unpinned = signed_out.post_json("/api/memory/unpin", {"path": it["logging"]})

    assert pinned.json() == {"path": it["logging"], "pinned": True}
    assert [one["pinned"] for one in listed] == [True]
    assert unpinned.json() == {"path": it["logging"], "pinned": False}


def test_history_and_versions_read_by_path_for_team_memory_too(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-six", 1206)

    versions = signed_out.get(f"/api/memory/history?{urlencode({'path': it['logging']})}").json()["versions"]
    text = signed_out.get(
        f"/api/memory/version?{urlencode({'path': it['logging'], 'commit': versions[0]['commit']})}"
    ).json()["text"]

    assert [version["message"].split(":")[0] for version in versions] == ["Promote", "Remember"]
    assert "one JSON object per line" in text


def test_search_spans_team_memory_and_every_project(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-seven", 1207)
    in_payments = it["owner"].in_project(it["payments"], "payments-api")
    in_payments.call(
        "remember",
        title="Refunds use the pnpm workspace",
        summary="Refunds live in the pnpm workspace.",
        type="architecture",
        body="The refunds service lives in the pnpm workspace with billing.",
    )

    found = signed_out.get("/api/search?query=pnpm").json()["results"]

    assert {(hit["title"], hit["project_id"]) for hit in found} >= {
        ("Use pnpm, not npm", it["billing"]),
        ("Refunds use the pnpm workspace", it["payments"]),
    }


def test_a_restricted_project_stays_out_of_the_files_of_anyone_outside_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-eight", 1208)
    add(signed_out, "emp-2", "Dana Dev", "dana-files-eight")
    signed_out.post_json(f"/api/projects/{it['billing']}/restrict", {"restricted": True})
    dana = signed_in(console, "dana-files-eight", 1209)

    top = files(dana)
    shared = "projects/" + it["billing"] + "/shared"
    inside = dana.get(f"/api/files?{urlencode({'folder': shared})}")
    read = dana.get(f"/api/memory?{urlencode({'path': it['pnpm']})}")
    found = dana.get("/api/search?query=pnpm").json()["results"]
    team = memory(dana, it["logging"])

    assert [one["name"] for one in top["folders"]] == ["Team memory", "Payments"]
    assert inside.status_code == 403
    assert "is restricted" in inside.json()["message"]
    assert read.status_code == 403
    assert all(hit["project_id"] != it["billing"] for hit in found)
    assert team["title"] == "Every service logs JSON"
    dana.close()


def test_the_projects_list_says_which_projects_are_restricted(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-nine", 1210)
    signed_out.post_json(f"/api/projects/{it['payments']}/restrict", {"restricted": True})

    listed = signed_out.get("/api/projects").json()["projects"]

    assert [(one["name"], one["restricted"]) for one in listed] == [("Billing", False), ("Payments", True)]


def test_a_member_reads_every_folder_of_an_open_project(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-ten", 1211)
    add(signed_out, "emp-2", "Dana Dev", "dana-files-ten")
    dana = signed_in(console, "dana-files-ten", 1212)

    personal = files(dana, f"projects/{it['billing']}/people/E1001/gotchas")

    assert [one["title"] for one in personal["memories"]] == ["My staging trick"]
    assert memory(dana, it["note"])["author"] == "E1001"
    dana.close()


def test_nothing_outside_the_team_folder_can_be_listed(console: Console, signed_out: ConsoleClient) -> None:
    a_team_with_memory(console, signed_out, "olive-files-eleven", 1213)

    escaped = signed_out.get(f"/api/files?{urlencode({'folder': '../..'})}")

    assert escaped.status_code == 403


def test_a_folder_lists_everything_beneath_it_when_asked(console: Console, signed_out: ConsoleClient) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-twelve", 1214)

    deep = signed_out.get(f"/api/files?{urlencode({'folder': 'projects/' + it['billing'], 'deep': '1'})}").json()

    sections = {section["path"].split("/", 2)[2]: section for section in deep["inside"]}
    assert set(sections) >= {"people", "people/E1001", "people/E1001/gotchas", "shared", "shared/conventions"}
    assert sections["shared/conventions"]["depth"] == 2
    assert sections["shared"]["count"] == 1
    assert [one["title"] for one in sections["shared/conventions"]["memories"]] == ["Use pnpm, not npm"]
    assert sections["shared/conventions"]["memories"][0]["changed"] is not None
    assert files(signed_out, f"projects/{it['billing']}")["inside"] == []


def test_a_projects_accepted_memory_is_listed_before_its_members_personal_memory(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = a_team_with_memory(console, signed_out, "olive-files-thirteen", 1215)
    billing = f"projects/{it['billing']}"

    listed = files(signed_out, billing)
    deep = signed_out.get(f"/api/files?{urlencode({'folder': billing, 'deep': '1'})}").json()

    assert [one["path"] for one in listed["folders"]] == [f"{billing}/shared", f"{billing}/people"]
    beneath = [section["path"].removeprefix(billing + "/") for section in deep["inside"]]
    assert beneath.index("shared/conventions") < beneath.index("people")
    assert beneath.index("people") < beneath.index("people/E1001")
