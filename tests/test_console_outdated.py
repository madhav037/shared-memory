"""The console shows which memories are possibly outdated: on a memory's page and in its folder's list."""

from __future__ import annotations

from datetime import datetime

from tests.support import Console, ConsoleClient, ask, promote_keeping_both, signed_in_owner


def a_memory(title: str, topic: str | None = None) -> dict[str, str]:
    memory = {"title": title, "summary": f"{title}.", "type": "convention", "body": f"{title}, every time."}
    if topic is not None:
        memory["topic"] = topic
    return memory


def test_a_memory_unused_for_long_is_possibly_outdated_on_its_page_and_in_its_folder(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-console-outdated", 2191)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    unused = promote_keeping_both(in_project, a_memory("Use pnpm, not npm"))
    written = console.clock()
    console.clock.advance(days=61)
    in_use = promote_keeping_both(in_project, a_memory("Lockfiles are committed"))
    signed_out.sign_in()  # the console's sign-in lapsed while the clock moved

    page = ask(signed_out, "/api/memory", path=unused)
    fresh_page = ask(signed_out, "/api/memory", path=in_use)
    folder = ask(signed_out, "/api/files", folder=unused.rsplit("/", 1)[0])
    deep = ask(signed_out, "/api/files", folder=f"projects/{project}/shared", deep="1")

    assert page["possibly_outdated"] is True
    assert datetime.fromisoformat(page["last_used"]) == written
    assert fresh_page["possibly_outdated"] is False
    listed = {memory["path"]: memory["possibly_outdated"] for memory in folder["memories"]}
    assert listed == {unused: True, in_use: False}
    inside = {memory["path"]: memory["possibly_outdated"] for section in deep["inside"] for memory in section["memories"]}
    assert inside == {unused: True, in_use: False}
    # Looking in the console is no use: the page still says so.
    assert ask(signed_out, "/api/memory", path=unused)["possibly_outdated"] is True
