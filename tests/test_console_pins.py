"""Pins from the console: what every session in a project is briefed with."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, added_context
from tests.test_console_browsing import ask, signed_in_owner


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[Session, str, Session]:
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    return owner, project, owner.in_project(project, "billing-api")


def a_promoted_memory(
    session: Session, title: str = "Use pnpm, not npm", topic: str | None = None, body: str | None = None
) -> str:
    saved = session.call(
        "remember",
        title=title,
        summary=f"{title}.",
        type="convention",
        body=body or f"{title}, every time, in every package.",
        topic=topic,
    )
    return promoted(session, saved["path"])


def promoted(session: Session, path: str) -> str:
    """Promote a memory, keeping anything similar that is already there."""
    result = session.call("promote", path=path, level="project")
    if result.get("status") == "similar_memories":
        result = session.call(
            "promote",
            path=path,
            level="project",
            reference=result["reference"],
            resolutions={one["path"]: "keep_both" for one in result["similar"]},
        )
    answer: str = result["path"]
    return answer


def pins(client: ConsoleClient, project: str) -> dict[str, Any]:
    return ask(client, f"/api/projects/{project}/pins")


def pin(client: ConsoleClient, project: str, path: str) -> Any:
    return client.post_json(f"/api/projects/{project}/pins", {"path": path})


def unpin(client: ConsoleClient, project: str, path: str) -> Any:
    return client.post_json(f"/api/projects/{project}/pins/remove", {"path": path})


def test_a_memory_shows_whether_it_is_pinned_and_is_pinned_from_its_page(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-one", 1001)
    path = a_promoted_memory(in_project)

    before = ask(signed_out, f"/api/projects/{project}/memory", path=path)
    pinned = pin(signed_out, project, path)
    after = ask(signed_out, f"/api/projects/{project}/memory", path=path)
    unpinned = unpin(signed_out, project, path)
    last = ask(signed_out, f"/api/projects/{project}/memory", path=path)

    assert before["pinned"] is False
    assert pinned.status_code == 200, pinned.text
    assert after["pinned"] is True
    assert unpinned.status_code == 200, unpinned.text
    assert last["pinned"] is False


def test_a_project_shows_everything_pinned_in_it(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-two", 1002)
    first = a_promoted_memory(in_project)
    second = a_promoted_memory(in_project, "Staging resets nightly")

    pin(signed_out, project, first)
    pin(signed_out, project, second)

    listed = pins(signed_out, project)
    assert {one["path"] for one in listed["pins"]} == {first, second}
    assert {one["title"] for one in listed["pins"]} == {"Use pnpm, not npm", "Staging resets nightly"}
    assert all(one["kind"] == "memory" and one["level"] == "project" for one in listed["pins"])
    assert all(one["pinned_by"] == "E1001" for one in listed["pins"])
    assert 0 < listed["tokens"] <= listed["cap"]


def test_what_is_pinned_appears_in_the_briefing_of_a_session(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-three", 1003)
    path = a_promoted_memory(in_project)

    pin(signed_out, project, path)

    assert "Use pnpm, not npm" in added_context(in_project.start())


def test_a_pin_over_the_briefing_cap_is_refused_with_what_is_already_pinned(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-four", 1004)
    first = a_promoted_memory(in_project)
    long_body = " ".join(
        ["Reconciliation chargebacks settlements subscriptions entitlements provisioning deprovisioning notifications"]
        * 63
    )
    second = a_promoted_memory(in_project, "Everything billing is made of", body=long_body)
    pin(signed_out, project, first)

    refused = pin(signed_out, project, second)

    assert refused.status_code == 403
    assert "over its cap" in refused.json()["message"]
    assert first in refused.json()["message"]
    assert [one["path"] for one in pins(signed_out, project)["pins"]] == [first]


def test_only_project_and_team_memory_can_be_pinned(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-five", 1005)
    personal = in_project.call(
        "remember", title="My own note", summary="Mine.", type="gotcha", body="Something I am still working out."
    )["path"]

    refused = pin(signed_out, project, personal)

    assert refused.status_code == 403
    assert "Only project memory and team memory can be pinned" in refused.json()["message"]


def test_pinning_a_topic_pins_its_index(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-six", 1006)
    a_promoted_memory(in_project, "Invoices are immutable", topic="invoicing")
    a_promoted_memory(in_project, "Invoices are numbered per year", topic="invoicing")
    topic = f"projects/{project}/shared/conventions/invoicing"

    pinned = pin(signed_out, project, topic)

    assert pinned.status_code == 200, pinned.text
    assert [(one["path"], one["kind"], one["title"]) for one in pins(signed_out, project)["pins"]] == [
        (topic, "topic", "invoicing")
    ]
    briefing = added_context(in_project.start())
    assert "Invoices are immutable" in briefing
    assert "Invoices are numbered per year" in briefing


def test_the_tree_says_which_folders_are_topics_and_which_memories_are_pinned(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-seven", 1007)
    loose = a_promoted_memory(in_project)
    a_promoted_memory(in_project, "Invoices are immutable", topic="invoicing")
    pin(signed_out, project, loose)

    tree = ask(signed_out, f"/api/projects/{project}/tree")

    folders = {folder["folder"]: folder for folder in tree["folders"]}
    topic = f"projects/{project}/shared/conventions/invoicing"
    assert folders[topic]["pinnable"] is True
    assert folders[topic]["pinned"] is False
    assert folders[f"projects/{project}/shared/conventions"]["pinnable"] is False
    pinned = [m["path"] for folder in tree["folders"] for m in folder["memories"] if m["pinned"]]
    assert pinned == [loose]


def test_pins_and_unpins_are_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-eight", 1008)
    path = a_promoted_memory(in_project)

    pin(signed_out, project, path)
    unpin(signed_out, project, path)

    log = signed_out.get(f"/api/audit?project={project}").json()["events"]
    assert [event["kind"] for event in log][:2] == ["memory_unpinned", "memory_pinned"]
    assert {event["target"] for event in log[:2]} == {path}
    assert {event["actor"] for event in log[:2]} == {"E1001"}


def test_unpinning_something_that_is_not_pinned_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-pins-nine", 1009)
    path = a_promoted_memory(in_project)

    refused = unpin(signed_out, project, path)

    assert refused.status_code == 403
    assert "is not pinned" in refused.json()["message"]
