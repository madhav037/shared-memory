from __future__ import annotations

import subprocess

from tests.support import NPM, PNPM, Session, Team, added_context, promote_now, promote_superseding


RETRIES = {
    "title": "Billing retries three times",
    "summary": "Failed charges are retried three times.",
    "type": "convention",
    "body": "The billing service retries a failed card charge three times before giving up.",
}


def test_an_author_retires_their_memory_at_once_in_one_commit(team: Team, owner: Session) -> None:
    path = promote_now(owner, RETRIES)

    result = owner.call("retire", path=path)

    subject = subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert result == {"status": "retired", "path": path}
    assert owner.call("read", path=path)["status"] == "retired"
    assert subject == "Retire: Billing retries three times"


def test_a_retired_memory_stays_readable_but_leaves_search_recall_and_briefing(owner: Session) -> None:
    path = promote_now(owner, RETRIES)
    owner.call("pin", path=path)

    owner.call("retire", path=path)

    assert owner.call("read", path=path)["title"] == RETRIES["title"]
    assert path not in [r["path"] for r in owner.call("search", query="how many times are charges retried")["results"]]
    assert path not in added_context(owner.prompt("how many times does billing retry a failed charge?"))
    assert path not in added_context(owner.start())


def test_retiring_another_authors_memory_raises_a_retire_challenge(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RETRIES)

    raised = dana.call("retire", path=path)

    assert raised["status"] == "challenge_raised"
    assert owner.call("read", path=path)["status"] == "active"
    assert f"Challenge {raised['challenge_id']} by emp-2: retire it." in added_context(owner.start())


def test_a_retire_challenges_reasoning_is_folded_into_the_authors_briefing_and_prompt(
    owner: Session, dana: Session
) -> None:
    path = promote_now(owner, RETRIES)

    raised = dana.call("retire", path=path, reasoning="We stopped retrying failed charges last quarter.")

    briefing = added_context(owner.start())
    prompt = added_context(owner.prompt("write a haiku about cats"))

    for context in (briefing, prompt):
        assert f"Challenge {raised['challenge_id']} by emp-2: retire it" in context
        assert "We stopped retrying failed charges last quarter." in context


def test_omitting_reasoning_leaves_the_retire_notice_exactly_as_before(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RETRIES)

    raised = dana.call("retire", path=path)

    briefing = added_context(owner.start())

    assert f"Challenge {raised['challenge_id']} by emp-2: retire it." in briefing
    assert "reasoning" not in briefing.lower()


def test_accepting_a_retire_challenge_retires_the_memory(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RETRIES)
    raised = dana.call("retire", path=path)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert owner.call("read", path=path)["status"] == "retired"


def test_rejecting_a_retire_challenge_leaves_the_memory_active(owner: Session, dana: Session) -> None:
    path = promote_now(owner, RETRIES)
    raised = dana.call("retire", path=path)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert owner.call("read", path=path)["status"] == "active"


def test_personal_memory_is_deleted_not_retired(owner: Session) -> None:
    personal = owner.call("remember", **RETRIES)["path"]

    assert "delete_memory" in owner.refusal("retire", path=personal)


def test_a_pin_moves_to_the_memory_that_supersedes_it(owner: Session) -> None:
    old = promote_now(owner, NPM)
    owner.call("pin", path=old)

    new = promote_superseding(owner, PNPM, target=old)["path"]
    briefing = added_context(owner.start())

    assert f"({new})" in briefing
    assert f"({old})" not in briefing


def test_a_pin_moves_when_a_challenge_supersedes_the_pinned_memory(owner: Session, dana: Session) -> None:
    old = promote_now(owner, NPM)
    owner.call("pin", path=old)
    raised = promote_superseding(dana, PNPM, target=old)

    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert f"({accepted['path']})" in added_context(owner.start())


def test_retiring_a_pinned_memory_removes_its_pin(owner: Session, dana: Session) -> None:
    mine = promote_now(owner, RETRIES)
    owner.call("pin", path=mine)
    owner.call("retire", path=mine)

    assert "not pinned" in owner.refusal("unpin", path=mine)
