from __future__ import annotations

import subprocess
from typing import Any

from tests.support import Session, Team, added_context

FLAKY_UPLOADS = {
    "title": "Large uploads time out behind the proxy",
    "summary": "Uploads over 50 MB fail with a 504 from the proxy.",
    "body": "Uploading a file larger than 50 MB fails with a 504 Gateway Timeout from the proxy.\n\n"
    "Workaround: upload large files in chunks with the resumable upload endpoint.",
}
FLAKY_UPLOADS_AGAIN = {
    "title": "Big uploads time out at the proxy",
    "summary": "Uploads larger than 50 MB fail with a proxy 504.",
    "body": "Uploading files bigger than 50 MB fails with a 504 Gateway Timeout returned by the proxy.\n\n"
    "Workaround: send large files in chunks through the resumable upload endpoint.",
}
UPLOAD_LIMIT = {
    "title": "Upload size limit",
    "summary": "Uploads over 50 MB time out with a 504 at the proxy.",
    "type": "gotcha",
    "body": "Uploading a file larger than 50 MB fails with a 504 Gateway Timeout from the proxy.",
}


def saved(session: Session, issue: dict[str, str], **extra: Any) -> str:
    result = session.call("save_known_issue", **issue, **extra)
    if result["status"] == "similar_memories":
        keep_all = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("save_known_issue", **issue, reference=result["reference"], resolutions=keep_all)
    assert result["status"] == "saved", result
    path: str = result["path"]
    return path


def in_project_memory(session: Session, memory: dict[str, str]) -> str:
    personal = session.call("remember", **memory)["path"]
    result = session.call("promote", path=personal, level="project")
    if result["status"] == "similar_memories":
        keep_all = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("promote", path=personal, level="project", reference=result["reference"], resolutions=keep_all)
    path: str = result["path"]
    return path


def test_a_known_issue_goes_straight_into_project_memory(owner: Session, project: str) -> None:
    result = owner.call("save_known_issue", **FLAKY_UPLOADS)
    memory = owner.call("read", path=result["path"])

    assert (result["status"], result["level"]) == ("saved", "project")
    assert result["path"].startswith(f"projects/{project}/shared/known-issues/")
    assert (memory["level"], memory["type"], memory["author"], memory["status"]) == (
        "project",
        "known_issue",
        "owner-1",
        "active",
    )
    assert memory["title"] == FLAKY_UPLOADS["title"]


def test_saving_a_known_issue_is_one_commit(team: Team, owner: Session) -> None:
    path = owner.call("save_known_issue", **FLAKY_UPLOADS)["path"]

    changed = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "show", "--name-status", "--format=%s", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert changed.startswith(f"Known issue: {FLAKY_UPLOADS['title']}")
    assert f"{team.code}/{path}" in changed


def test_a_known_issue_without_a_workaround_line_is_refused(owner: Session) -> None:
    no_workaround = {**FLAKY_UPLOADS, "body": "Uploading a file larger than 50 MB fails with a 504 from the proxy."}

    refusal = owner.refusal("save_known_issue", **no_workaround)

    assert "Workaround:" in refusal
    assert "none known" in refusal
    assert owner.call("tree", level="project") == {"folders": []}


def test_saying_no_workaround_is_known_is_enough(owner: Session) -> None:
    none_known = {**FLAKY_UPLOADS, "body": "Uploads over 50 MB fail with a 504.\n\nWorkaround: none known."}

    assert owner.call("save_known_issue", **none_known)["status"] == "saved"


def test_a_workaround_can_be_its_own_section(owner: Session) -> None:
    sectioned = {**FLAKY_UPLOADS, "body": "Uploads over 50 MB fail with a 504.\n\n## Workaround\n\nUpload in chunks."}

    assert owner.call("save_known_issue", **sectioned)["status"] == "saved"


def test_a_workaround_heading_with_nothing_under_it_is_refused(owner: Session) -> None:
    empty = {**FLAKY_UPLOADS, "body": "Uploads over 50 MB fail with a 504.\n\n## Workaround\n"}

    assert "Workaround:" in owner.refusal("save_known_issue", **empty)


def test_a_known_issue_is_never_personal_memory(owner: Session) -> None:
    refusal = owner.refusal("remember", **FLAKY_UPLOADS, type="known_issue")

    assert "save_known_issue" in refusal


def test_similar_project_memories_are_returned_before_it_lands(owner: Session, dana: Session) -> None:
    existing = saved(dana, FLAKY_UPLOADS)

    result = owner.call("save_known_issue", **FLAKY_UPLOADS_AGAIN)

    assert result["status"] == "similar_memories"
    assert result["reference"]
    assert [(similar["path"], similar["type"], similar["author"]) for similar in result["similar"]] == [
        (existing, "known_issue", "emp-2")
    ]
    assert "link" in result["next"] and "keep_both" in result["next"]
    assert [m["path"] for f in owner.call("tree", level="project")["folders"] for m in f["memories"]] == [existing]


def test_keep_both_lands_the_known_issue(owner: Session, dana: Session) -> None:
    existing = saved(dana, FLAKY_UPLOADS)
    first = owner.call("save_known_issue", **FLAKY_UPLOADS_AGAIN)

    result = owner.call(
        "save_known_issue", **FLAKY_UPLOADS_AGAIN, reference=first["reference"], resolutions={existing: "keep_both"}
    )

    assert result["status"] == "saved"
    assert owner.call("read", path=result["path"])["level"] == "project"
    assert owner.call("read", path=existing)["status"] == "active"


def test_linking_to_an_existing_known_issue_saves_no_second_one(owner: Session, dana: Session) -> None:
    existing = saved(dana, FLAKY_UPLOADS)
    first = owner.call("save_known_issue", **FLAKY_UPLOADS_AGAIN)

    result = owner.call(
        "save_known_issue", **FLAKY_UPLOADS_AGAIN, reference=first["reference"], resolutions={existing: "link"}
    )

    assert (result["status"], result["path"]) == ("linked", existing)
    assert [m["path"] for f in owner.call("tree", level="project")["folders"] for m in f["memories"]] == [existing]


def test_only_a_known_issue_can_be_linked_to(owner: Session, dana: Session) -> None:
    gotcha = in_project_memory(dana, UPLOAD_LIMIT)
    first = owner.call("save_known_issue", **FLAKY_UPLOADS)
    assert [similar["path"] for similar in first["similar"]] == [gotcha]

    refusal = owner.refusal(
        "save_known_issue", **FLAKY_UPLOADS, reference=first["reference"], resolutions={gotcha: "link"}
    )

    assert "link only to a known issue" in refusal


def test_cancel_saves_nothing(owner: Session, dana: Session) -> None:
    existing = saved(dana, FLAKY_UPLOADS)
    first = owner.call("save_known_issue", **FLAKY_UPLOADS_AGAIN)

    result = owner.call(
        "save_known_issue", **FLAKY_UPLOADS_AGAIN, reference=first["reference"], resolutions={existing: "cancel"}
    )

    assert result == {"status": "cancelled"}
    assert [m["path"] for f in owner.call("tree", level="project")["folders"] for m in f["memories"]] == [existing]


def test_every_similar_memory_needs_a_resolution(owner: Session, dana: Session) -> None:
    saved(dana, FLAKY_UPLOADS)
    first = owner.call("save_known_issue", **FLAKY_UPLOADS_AGAIN)

    refusal = owner.refusal("save_known_issue", **FLAKY_UPLOADS_AGAIN, reference=first["reference"], resolutions={})

    assert "resolution for every similar memory" in refusal


def test_an_unknown_reference_is_refused(owner: Session) -> None:
    refusal = owner.refusal("save_known_issue", **FLAKY_UPLOADS, reference="nope", resolutions={})

    assert "reference" in refusal


def test_a_matching_prompt_recalls_the_known_issue(owner: Session, dana: Session) -> None:
    path = saved(owner, FLAKY_UPLOADS)

    context = added_context(dana.prompt("upload a 200 MB video file through the proxy"))

    assert path in context
    assert "[project memory]" in context


def test_search_finds_the_known_issue(owner: Session, dana: Session) -> None:
    path = saved(owner, FLAKY_UPLOADS)

    everything = dana.call("search", query="large upload 504 gateway timeout")["results"]
    known_issues = dana.call("search", query="large upload 504 gateway timeout", type="known_issue")["results"]

    assert everything[0]["path"] == path
    assert [(hit["path"], hit["type"]) for hit in known_issues] == [(path, "known_issue")]


def cards(session: Session) -> list[dict[str, Any]]:
    columns = session.call("board")["columns"]
    return [card for column in columns.values() for card in column]


def test_saving_a_known_issue_adds_a_to_do_card_to_fix_it(owner: Session) -> None:
    result = owner.call("save_known_issue", **FLAKY_UPLOADS)

    (card,) = cards(owner)
    assert result["card"] == card["number"]
    assert (card["column"], card["title"], card["known_issues"]) == (
        "to_do",
        f"Fix: {FLAKY_UPLOADS['title']}",
        [result["path"]],
    )
    assert card["description"] == FLAKY_UPLOADS["summary"]


def test_a_named_card_is_linked_instead_of_adding_one(owner: Session) -> None:
    number = owner.call("add_card", title="Move uploads to direct-to-storage")["number"]

    result = owner.call("save_known_issue", **FLAKY_UPLOADS, card=number)

    assert result["card"] == number
    assert [(card["number"], card["known_issues"]) for card in cards(owner)] == [(number, [result["path"]])]


def test_a_card_the_board_lacks_is_refused_and_nothing_is_saved(owner: Session) -> None:
    refusal = owner.refusal("save_known_issue", **FLAKY_UPLOADS, card=42)

    assert "no card 42" in refusal
    assert owner.call("tree", level="project") == {"folders": []}
    assert cards(owner) == []


def test_linking_to_an_existing_known_issue_links_a_named_card_to_it(owner: Session, dana: Session) -> None:
    existing = saved(dana, FLAKY_UPLOADS)
    number = owner.call("add_card", title="Chunk every upload")["number"]
    first = owner.call("save_known_issue", **FLAKY_UPLOADS_AGAIN, card=number)

    result = owner.call(
        "save_known_issue",
        **FLAKY_UPLOADS_AGAIN,
        card=number,
        reference=first["reference"],
        resolutions={existing: "link"},
    )

    assert (result["status"], result["path"], result["card"]) == ("linked", existing, number)
    assert [card["known_issues"] for card in cards(owner) if card["number"] == number] == [[existing]]
    assert len(cards(owner)) == 2


def test_a_member_links_a_known_issue_to_a_card_with_no_assignee(owner: Session, dana: Session) -> None:
    number = owner.call("add_card", title="Move uploads to direct-to-storage")["number"]

    result = dana.call("save_known_issue", **FLAKY_UPLOADS, card=number)

    assert [card["known_issues"] for card in cards(owner)] == [[result["path"]]]


def test_a_card_someone_else_is_assigned_is_refused_and_nothing_is_saved(
    owner: Session, dana: Session, cole: Session
) -> None:
    number = owner.call("add_card", title="Move uploads to direct-to-storage")["number"]
    cole.call("claim_card", number=number)

    refusal = dana.refusal("save_known_issue", **FLAKY_UPLOADS, card=number)

    assert "Cole Coder (emp-3)" in refusal
    assert owner.call("tree", level="project") == {"folders": []}
    assert [card["known_issues"] for card in cards(owner)] == [[]]
    assert cole.call("save_known_issue", **FLAKY_UPLOADS, card=number)["card"] == number
