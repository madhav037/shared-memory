"""The console reads the commit messages this server writes.

`console/src/lib/versions.ts` turns a commit message into a sentence a member can read — "First written by
Olive Owner", "Promoted by Olive Owner" — by matching the word this server puts at the front of it. Matching
none of them is not an error there: it prints the message raw, which looks almost right. So a message reworded
on this side would quietly read as a bare commit line on that side, and nothing would fail.

Nothing else declares that agreement. These tests are it, read from the words the console actually matches on
rather than repeated here, so rewording either side is what goes red.
"""

from __future__ import annotations

import re

from tests.support import (
    NPM,
    PNPM,
    REPO_ROOT,
    Console,
    ConsoleClient,
    Session,
    add,
    ask,
    challenge,
    promote_now,
    signed_in_owner,
)

VERSIONS = (REPO_ROOT / "console" / "src" / "lib" / "versions.ts").read_text(encoding="utf-8")

#: The one message shape versions.ts matches with a pattern rather than a word at the front.
ACCEPTED = re.compile(r"^Accept challenge \d+: (retire )?.+$")


def verbs_the_console_knows() -> set[str]:
    found = set(re.findall(r'case "([A-Za-z]+)":', VERSIONS))
    assert found, "versions.ts no longer switches on the word at the front of a commit message"
    return found


def unreadable(messages: list[str]) -> list[str]:
    """The messages the console would print raw, because it recognises nothing in them."""
    assert "Accept challenge (" in VERSIONS, "versions.ts no longer matches an accepted challenge"
    known = verbs_the_console_knows()
    return [one for one in messages if not ACCEPTED.match(one) and one.split(": ", 1)[0] not in known]


def messages(client: ConsoleClient, project: str, path: str) -> list[str]:
    versions = ask(client, f"/api/projects/{project}/memory/history", path=path)["versions"]
    return [str(version["message"]) for version in versions]


def test_writing_editing_promoting_and_retiring_all_read_as_sentences(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-commits", 1601)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")

    saved = in_project.call("remember", **NPM)["path"]
    in_project.call("edit_memory", path=saved, body="We use npm for every package, and nothing else.")
    promoted = in_project.call("promote", path=saved, level="project")["path"]
    in_project.call("retire", path=promoted)

    written = messages(signed_out, project, promoted)

    assert unreadable(written) == []
    assert {one.split(": ", 1)[0] for one in written} == {"Remember", "Edit", "Promote", "Retire"}


def test_an_accepted_supersede_challenge_reads_as_a_sentence(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-supersede-commits", 1602)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    target = promote_now(in_project, NPM)
    dana = Session(console.server, add(signed_out, "emp-commits", "Dana Dev", "dana-commits")["personal_token"])
    raised = challenge(dana.in_project(project, "billing-api"), PNPM, target)

    decided = signed_out.post_json(f"/api/challenges/{raised['challenge_id']}/decide", {"decision": "accept"})
    assert decided.status_code == 200, decided.text

    written = messages(signed_out, project, target)

    assert unreadable(written) == []
    assert any(ACCEPTED.match(one) for one in written), written


def test_an_accepted_retire_challenge_reads_as_a_sentence(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-retire-commits", 1603)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    target = promote_now(in_project, NPM)
    dana = Session(console.server, add(signed_out, "emp-retires", "Dana Dev", "dana-retires")["personal_token"])

    asked = dana.in_project(project, "billing-api").call("retire", path=target)
    decided = signed_out.post_json(f"/api/challenges/{asked['challenge_id']}/decide", {"decision": "accept"})
    assert decided.status_code == 200, decided.text

    written = messages(signed_out, project, target)

    assert unreadable(written) == []
    assert any(one.startswith("Accept challenge ") and " retire " in one for one in written), written
