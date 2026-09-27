from __future__ import annotations

from tests.support import NPM, PNPM, Session, Team, added_context, challenge, promote_now


def test_any_member_can_decide_a_challenge_after_three_days(team: Team, owner: Session, dana: Session, cole: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    team.server.clock.advance(days=2, hours=23)
    too_early = cole.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    team.server.clock.advance(hours=1)
    decided = cole.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "until it has been open for 3 days" in too_early
    assert decided["status"] == "accepted"


def test_challenges_open_three_days_are_in_every_members_briefing(team: Team, owner: Session, dana: Session, cole: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)
    team.server.clock.advance(days=3)

    assert f"Challenge {raised['challenge_id']} by emp-2" in added_context(cole.start())


def test_challenges_against_a_removed_members_memory_can_be_decided_at_once(team: Team, dana: Session, cole: Session) -> None:
    target = promote_now(dana, NPM)
    raised = challenge(cole, PNPM, target)

    team.owner().call("remove_member", member_id="emp-2")
    decided = team.owner().in_project(cole.project or "").call(
        "decide_challenge", challenge_id=raised["challenge_id"], decision="reject"
    )

    assert decided["status"] == "rejected"
    assert cole.call("read", path=target)["author"] == "emp-2"


def test_a_removed_members_challenge_stays_open_and_can_be_accepted(team: Team, owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    team.owner().call("remove_member", member_id="emp-2")
    still_open = owner.call("read", path=target)["open_challenges"]
    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert [c["challenge_id"] for c in still_open] == [raised["challenge_id"]]
    assert owner.call("read", path=accepted["path"])["author"] == "emp-2"


def test_any_member_can_promote_a_removed_members_personal_memory(team: Team, dana: Session, cole: Session) -> None:
    danas = dana.call("remember", **PNPM)["path"]
    team.owner().call("remove_member", member_id="emp-2")

    result = cole.call("promote", path=danas, level="project")
    promoted = cole.call("read", path=result["path"])

    assert (promoted["author"], promoted["promoted_by"], promoted["level"]) == ("emp-2", "emp-3", "project")


def test_an_active_members_personal_memory_still_cannot_be_promoted_by_others(dana: Session, cole: Session) -> None:
    danas = dana.call("remember", **PNPM)["path"]

    assert "your own personal memory" in cole.refusal("promote", path=danas, level="project")


def test_promoted_by_is_kept_when_promoting_a_removed_members_memory_raises_a_challenge(
    team: Team, owner: Session, dana: Session, cole: Session
) -> None:
    target = promote_now(owner, NPM)
    danas = dana.call("remember", **PNPM)["path"]
    team.owner().call("remove_member", member_id="emp-2")
    first = cole.call("promote", path=danas, level="project")
    raised = cole.call(
        "promote",
        path=danas,
        level="project",
        reference=first["reference"],
        resolutions={s["path"]: ("supersede" if s["path"] == target else "keep_both") for s in first["similar"]},
    )

    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert owner.call("read", path=accepted["path"])["promoted_by"] == "emp-3"
