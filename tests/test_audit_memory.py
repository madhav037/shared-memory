"""Memory changes made from Claude sessions, as the audit log records them."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, signed_in_owner


def log(client: ConsoleClient, **filters: Any) -> list[dict[str, Any]]:
    query = "&".join(f"{name}={value}" for name, value in filters.items() if value is not None)
    response = client.get(f"/api/audit?{query}")
    assert response.status_code == 200, response.text
    events: list[dict[str, Any]] = response.json()["events"]
    return events


def kinds(events: list[dict[str, Any]]) -> list[str]:
    return [event["kind"] for event in events]


def a_project(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[Session, str, Session]:
    """A signed-in owner, a project, and that owner's session working in it."""
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    return owner, project, owner.in_project(project, "billing-api")


def a_memory(session: Session, title: str = "Use pnpm, not npm") -> str:
    path: str = session.call(
        "remember", title=title, summary=f"{title}.", type="convention", body=f"{title}, every time."
    )["path"]
    return path


def test_saving_editing_and_deleting_a_memory_are_recorded_with_the_project_and_the_path(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-one", 901)

    path = a_memory(in_project)
    in_project.call("edit_memory", path=path, body="We use pnpm for every package.")
    in_project.call("delete_memory", path=path)

    recorded = log(signed_out, project=project)
    assert kinds(recorded) == ["memory_deleted", "memory_edited", "memory_saved", "project_created"]
    assert {event["target"] for event in recorded if event["kind"].startswith("memory_")} == {path}
    assert {event["actor"] for event in recorded} == {"E1001"}


def test_promoting_and_superseding_are_recorded(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-two", 902)
    first = a_memory(in_project)
    promoted = in_project.call("promote", path=first, level="project")["path"]
    second = a_memory(in_project, "Use pnpm everywhere")
    similar = in_project.call("promote", path=second, level="project")

    in_project.call(
        "promote",
        path=second,
        level="project",
        reference=similar["reference"],
        resolutions={one["path"]: "supersede" for one in similar["similar"]},
    )

    recorded = log(signed_out, project=project)
    assert kinds(recorded)[:2] == ["memory_superseded", "memory_promoted"]
    assert recorded[0]["target"] == promoted
    assert recorded[1]["detail"]["level"] == "project"


def test_retiring_a_memory_is_recorded(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-three", 903)
    promoted = in_project.call("promote", path=a_memory(in_project), level="project")["path"]

    in_project.call("retire", path=promoted)

    assert kinds(log(signed_out, project=project, kind="memory_retired")) == ["memory_retired"]
    assert log(signed_out, project=project, kind="memory_retired")[0]["target"] == promoted


def test_pinning_and_unpinning_are_recorded(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-four", 904)
    promoted = in_project.call("promote", path=a_memory(in_project), level="project")["path"]

    in_project.call("pin", path=promoted)
    in_project.call("unpin", path=promoted)

    recorded = log(signed_out, project=project)
    assert kinds(recorded)[:2] == ["memory_unpinned", "memory_pinned"]
    assert recorded[1]["detail"] == {"pinned": "memory", "level": "project", "agent": "another agent"}


def test_a_challenge_raised_and_decided_from_a_session_is_recorded(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_project(console, signed_out, "olive-changes-five", 905)
    promoted = in_project.call("promote", path=a_memory(in_project), level="project")["path"]
    dana = Session(console.server, owner.call("add_member", employee_id="emp-2", name="Dana Dev")["personal_token"])
    dana_in_project = dana.in_project(project, "billing-api")
    challenger = a_memory(dana_in_project, "Use npm, not pnpm")
    similar = dana_in_project.call("promote", path=challenger, level="project")
    raised = dana_in_project.call(
        "promote",
        path=challenger,
        level="project",
        reference=similar["reference"],
        resolutions={one["path"]: "supersede" for one in similar["similar"]},
    )

    in_project.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    decided = log(signed_out, project=project, kind="challenge_decided")
    challenged = log(signed_out, project=project, kind="challenge_raised")
    assert decided[0]["detail"] == {
        "challenge_id": raised["challenge_id"],
        "decision": "accepted",
        "challenge": "supersede",
        "agent": "another agent",
    }
    assert decided[0]["actor"] == "E1001"
    assert challenged[0]["actor"] == "emp-2"
    assert challenged[0]["target"] == promoted


def test_the_log_filters_memory_changes_by_project_member_and_kind(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, billing, in_billing = a_project(console, signed_out, "olive-changes-six", 906)
    payments = owner.call("create_project", name="Payments")["project_id"]
    in_payments = owner.in_project(payments, "payments-api")
    dana = Session(console.server, owner.call("add_member", employee_id="emp-2", name="Dana Dev")["personal_token"])
    a_memory(in_billing)
    a_memory(in_payments, "Refunds are asynchronous")
    a_memory(dana.in_project(billing, "billing-api"), "Dana's own note")

    in_billing_only = log(signed_out, project=billing, kind="memory_saved")
    by_dana = log(signed_out, member="emp-2", kind="memory_saved")

    assert [event["actor"] for event in in_billing_only] == ["emp-2", "E1001"]
    assert [event["project_id"] for event in by_dana] == [billing]


def test_the_log_still_holds_no_memory_content(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-seven", 907)

    in_project.call(
        "remember",
        title="Staging resets nightly",
        summary="Staging is wiped at 02:17 UTC.",
        type="gotcha",
        body="A body that must never be copied into the audit log.",
    )

    assert "must never be copied" not in str(log(signed_out, project=project))
    assert "02:17" not in str(log(signed_out, project=project))


def test_what_the_memory_tools_answer_is_unchanged(console: Console, signed_out: ConsoleClient) -> None:
    _, _, in_project = a_project(console, signed_out, "olive-changes-eight", 908)

    saved = in_project.call(
        "remember", title="Use pnpm, not npm", summary="Billing uses pnpm.", type="convention", body="We use pnpm."
    )
    pinned = in_project.call("pin", path=in_project.call("promote", path=saved["path"], level="project")["path"])

    # remember also says which level it saved at and what to do about it, since that is the moment an agent chooses.
    assert set(saved) == {"path", "level", "next"}
    assert set(pinned) == {"pinned"}


def test_a_memory_change_records_the_coding_agent_it_came_from(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-agent", 911)

    path = a_memory(in_project.as_agent("codex-mcp-client"))

    saved = next(event for event in log(signed_out, project=project) if event["kind"] == "memory_saved")
    assert saved["detail"]["agent"] == "Codex"
    history = signed_out.get(f"/api/memory/history?path={path}").json()
    assert [version["agent"] for version in history["versions"]] == ["Codex"]


def test_each_coding_agent_is_named_the_way_members_know_it(console: Console, signed_out: ConsoleClient) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-agents", 912)
    reported = {
        "claude-code": "Claude Code",
        "codex-mcp-client": "Codex",
        "Visual Studio Code": "GitHub Copilot",
        "gemini-cli-mcp-client": "Gemini CLI",
        "cursor-vscode": "Cursor",
        "Windsurf": "Devin Desktop",
        "Cline": "Cline",
        "some-new-tool": "another agent",
    }

    for name in reported:
        a_memory(in_project.as_agent(name), f"Saved from {name}")

    saved = {
        event["target"].rsplit("/", 1)[-1]: event["detail"]["agent"]
        for event in log(signed_out, project=project)
        if event["kind"] == "memory_saved"
    }
    for name, known_as in reported.items():
        file = next(file for file in saved if file.startswith("saved-from-" + name.lower().replace(" ", "-")[:12]))
        assert saved[file] == known_as, name


def test_an_agent_that_does_not_say_what_it_is_is_recorded_as_another_agent(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, project, in_project = a_project(console, signed_out, "olive-changes-silent", 913)

    path = a_memory(in_project)

    saved = next(event for event in log(signed_out, project=project) if event["kind"] == "memory_saved")
    assert saved["target"] == path
    assert saved["detail"]["agent"] == "another agent"

