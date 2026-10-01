"""A known issue retires with the card that fixes it: moving the card to Done retires the known issue, or challenges it
when another member wrote it, and deleting the card leaves the known issue for the project's leads to see to."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from shared_memory.errors import Refused
from shared_memory.lifecycle import Lifecycle
from tests.support import Session, Team, added_context
from tests.test_card_claims import led_by_dana, the_card
from tests.test_known_issues import FLAKY_UPLOADS

STALE_PRICES = {
    "title": "The price cache serves stale prices after a deploy",
    "summary": "Prices stay stale for up to an hour after each deploy.",
    "body": "After a deploy the price cache keeps serving the old prices for up to an hour.\n\n"
    "Workaround: flush the price cache by hand once the deploy finishes.",
}


def fixed(session: Session, issue: dict[str, str]) -> tuple[str, int]:
    """A known issue saved by this member, and the To do card added to fix it."""
    result = session.call("save_known_issue", **issue)
    assert result["status"] == "saved", result
    return result["path"], result["card"]


def test_moving_the_card_to_done_retires_your_own_known_issue_in_one_commit(team: Team, owner: Session) -> None:
    path, number = fixed(owner, FLAKY_UPLOADS)

    moved = owner.call("update_card", number=number, column="done")

    subject = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert moved["column"] == "done"
    assert moved["known_issues_fixed"] == [{"status": "retired", "path": path}]
    assert owner.call("read", path=path)["status"] == "retired"
    assert subject == f"Retire: {FLAKY_UPLOADS['title']}"
    assert FLAKY_UPLOADS["title"] not in added_context(owner.start())


def test_moving_the_card_to_done_challenges_a_known_issue_another_member_wrote(owner: Session, dana: Session) -> None:
    path, number = fixed(dana, FLAKY_UPLOADS)

    moved = owner.call("update_card", number=number, column="done")

    (raised,) = moved["known_issues_fixed"]
    assert (raised["status"], raised["challenges"], raised["author"]) == ("challenge_raised", path, "emp-2")
    assert dana.call("read", path=path)["status"] == "active"
    assert (
        f"Challenge {raised['challenge_id']} by owner-1: retire it — reasoning: Card {number} "
        f'"Fix: {FLAKY_UPLOADS["title"]}", which was to fix this known issue, is done.' in added_context(dana.start())
    )


def test_the_author_accepting_the_challenge_retires_the_known_issue(owner: Session, dana: Session) -> None:
    path, number = fixed(dana, FLAKY_UPLOADS)
    (raised,) = owner.call("update_card", number=number, column="done")["known_issues_fixed"]

    dana.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert dana.call("read", path=path)["status"] == "retired"


def test_a_known_issue_already_retired_is_left_as_it_is(owner: Session) -> None:
    path, number = fixed(owner, FLAKY_UPLOADS)
    owner.call("retire", path=path)

    moved = owner.call("update_card", number=number, column="done")

    assert (moved["column"], moved["known_issues_fixed"]) == ("done", [])
    assert owner.call("read", path=path)["status"] == "retired"


def test_a_card_move_that_is_refused_retires_nothing(owner: Session, dana: Session, cole: Session) -> None:
    path, number = fixed(owner, FLAKY_UPLOADS)
    cole.call("claim_card", number=number)

    refusal = dana.refusal("update_card", number=number, column="done")

    assert "Cole Coder (emp-3)" in refusal
    assert the_card(owner, number)["column"] == "doing"
    assert owner.call("read", path=path)["status"] == "active"


def test_moving_a_card_within_done_retires_nothing_again(owner: Session, dana: Session) -> None:
    path, number = fixed(dana, FLAKY_UPLOADS)
    owner.call("update_card", number=number, column="done")

    moved = owner.call("update_card", number=number, position=1)

    assert "known_issues_fixed" not in moved


def failing_for(monkeypatch: pytest.MonkeyPatch, failing: str) -> None:
    """Make retiring one memory fail, as a save that can't be written would, and leave every other retire alone."""
    retire = Lifecycle.retire

    def retire_unless_failing(self: Lifecycle, caller: Any, path: str, reasoning: str | None = None) -> dict[str, Any]:
        if path == failing:
            raise OSError("The memory folder could not be written.")
        return retire(self, caller, path, reasoning)

    monkeypatch.setattr(Lifecycle, "retire", retire_unless_failing)


def test_a_known_issue_that_fails_to_retire_is_reported_and_the_others_still_retire(
    owner: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing, number = fixed(owner, FLAKY_UPLOADS)
    other = owner.call("save_known_issue", **STALE_PRICES, card=number)["path"]
    failing_for(monkeypatch, failing)

    moved = owner.call("update_card", number=number, column="done")

    not_retired, retired = moved["known_issues_fixed"]
    assert moved["column"] == "done"
    assert (not_retired["status"], not_retired["path"]) == ("not_retired", failing)
    assert "The memory folder could not be written." in not_retired["reason"]
    assert "retire" in not_retired["next"]
    assert f"move card {number} to Done again" in not_retired["next"]
    assert retired == {"status": "retired", "path": other}
    assert owner.call("read", path=failing)["status"] == "active"
    assert owner.call("read", path=other)["status"] == "retired"


def test_a_retire_that_is_refused_is_reported_with_the_refusal(owner: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    path, number = fixed(owner, FLAKY_UPLOADS)

    def refused(self: Lifecycle, caller: Any, path: str, reasoning: str | None = None) -> dict[str, Any]:
        raise Refused("This project's memory is being moved.")

    monkeypatch.setattr(Lifecycle, "retire", refused)

    (not_retired,) = owner.call("update_card", number=number, column="done")["known_issues_fixed"]

    assert (not_retired["status"], not_retired["path"]) == ("not_retired", path)
    assert not_retired["reason"] == "This project's memory is being moved."
    assert the_card(owner, number)["column"] == "done"


def test_moving_a_done_card_to_done_again_retires_the_known_issues_still_active(
    owner: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing, number = fixed(owner, FLAKY_UPLOADS)
    owner.call("save_known_issue", **STALE_PRICES, card=number)
    with monkeypatch.context() as broken:
        failing_for(broken, failing)
        owner.call("update_card", number=number, column="done")

    again = owner.call("update_card", number=number, column="done")

    assert again["column"] == "done"
    assert again["known_issues_fixed"] == [{"status": "retired", "path": failing}]
    assert owner.call("read", path=failing)["status"] == "retired"


def test_moving_a_done_card_to_done_again_raises_no_second_challenge(owner: Session, dana: Session) -> None:
    path, number = fixed(dana, FLAKY_UPLOADS)
    (raised,) = owner.call("update_card", number=number, column="done")["known_issues_fixed"]

    (again,) = owner.call("update_card", number=number, column="done")["known_issues_fixed"]

    assert (again["status"], again["challenge_id"], again["challenges"]) == (
        "challenge_raised",
        raised["challenge_id"],
        path,
    )
    assert added_context(dana.start()).count("retire it") == 1


def test_a_card_moved_anywhere_but_done_retires_nothing(owner: Session) -> None:
    path, number = fixed(owner, FLAKY_UPLOADS)

    moved = owner.call("update_card", number=number, column="doing")

    assert "known_issues_fixed" not in moved
    assert owner.call("read", path=path)["status"] == "active"


def test_deleting_a_linked_card_leaves_the_known_issue_and_tells_the_projects_leads(team: Team, dana: Session) -> None:
    lead, cole, _ = led_by_dana(team, dana)
    path, number = fixed(cole, FLAKY_UPLOADS)
    added_context(lead.start())

    cole.call("delete_card", number=number)

    told = added_context(lead.start())
    assert cole.call("read", path=path)["status"] == "active"
    assert cole.call("board")["columns"]["to_do"] == []
    assert f'Cole Coder (emp-3) deleted card {number} "Fix: {FLAKY_UPLOADS["title"]}"' in told
    assert path in told
    assert "still active" in told
    assert "deleted card" not in added_context(cole.start())


def test_deleting_a_card_with_no_known_issues_tells_no_one(team: Team, dana: Session) -> None:
    lead, cole, _ = led_by_dana(team, dana)
    number = cole.call("add_card", title="Split the invoice module")["number"]
    added_context(lead.start())

    cole.call("delete_card", number=number)

    assert "deleted card" not in added_context(lead.start())


def test_a_lead_who_deletes_a_linked_card_is_not_told_of_it(owner: Session) -> None:
    path, number = fixed(owner, FLAKY_UPLOADS)

    owner.call("delete_card", number=number)

    assert "deleted card" not in added_context(owner.start())
