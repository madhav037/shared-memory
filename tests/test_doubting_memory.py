"""A session doubts a memory it can read (#534, spec #502): it raises a challenge of kind doubt, naming a reason
(`misled`, or `contradicts_code` quoting the file and line), and a second raise with the same reason joins the open
doubt as a +1. Driven through the Session driver over HTTP."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tests.support import (
    REPO_ROOT,
    Console,
    ConsoleClient,
    Session,
    Team,
    add,
    added_context,
    create,
    member,
    promote_keeping_both,
    signed_in_owner,
)

TAX = {
    "title": "Sales tax is fifteen percent",
    "summary": "Invoices add fifteen percent sales tax.",
    "type": "convention",
    "body": "Every invoice adds a flat fifteen percent sales tax on the subtotal.",
}
WEBHOOKS = {
    "title": "Webhooks retry for a day",
    "summary": "A failed webhook is retried for twenty-four hours.",
    "type": "gotcha",
    "body": "The relay retries a failed webhook delivery with backoff for twenty-four hours before giving up.",
}
TAX_LINE = {"code_reference": "billing-api:src/tax.py:42", "quoted_line": "RATE = Decimal('0.20')"}


def doubt(session: Session, path: str, reason: str = "misled", **extra: Any) -> dict[str, Any]:
    raised: dict[str, Any] = session.call("challenge", path=path, reason=reason, **extra)
    return raised


def test_raising_a_doubt_with_the_reason_misled_opens_it_answering_its_id_not_joined_and_a_count_of_one(
    owner: Session, dana: Session
) -> None:
    path = promote_keeping_both(owner, TAX)

    raised = doubt(dana, path, reasoning="It told me to add fifteen percent; the invoices came out wrong.")

    assert raised == {"challenge_id": raised["challenge_id"], "joined": False, "count": 1}
    assert isinstance(raised["challenge_id"], int)
    assert [c["kind"] for c in dana.call("read", path=path)["open_challenges"]] == ["doubt"]


def test_a_doubt_that_contradicts_the_code_without_a_repository_file_and_line_is_refused(
    owner: Session, dana: Session
) -> None:
    path = promote_keeping_both(owner, TAX)
    quoted = TAX_LINE["quoted_line"]

    refusals = [
        dana.refusal("challenge", path=path, reason="contradicts_code", quoted_line=quoted),
        dana.refusal("challenge", path=path, reason="contradicts_code", code_reference="src/tax.py:42", quoted_line=quoted),
        dana.refusal(
            "challenge", path=path, reason="contradicts_code", code_reference="billing-api:src/tax.py", quoted_line=quoted
        ),
        dana.refusal("challenge", path=path, reason="contradicts_code", code_reference="billing-api:src/tax.py:42"),
    ]

    assert all("repository:path:line" in refusal for refusal in refusals[:3]), refusals
    assert "quoted_line" in refusals[3]
    assert dana.call("read", path=path)["open_challenges"] == []


def test_a_member_raises_a_doubt_against_their_own_memory_and_against_project_and_team_memory(
    owner: Session, dana: Session
) -> None:
    own = dana.call("remember", **WEBHOOKS)["path"]
    project = promote_keeping_both(owner, TAX)
    team = promote_keeping_both(owner, WEBHOOKS, level="team")

    raised = [doubt(dana, path) for path in (own, project, team)]

    assert [one["joined"] for one in raised] == [False, False, False]
    assert len({one["challenge_id"] for one in raised}) == 3
    for path in (own, project, team):
        assert [c["kind"] for c in dana.call("read", path=path)["open_challenges"]] == ["doubt"]


def test_raising_a_doubt_in_a_restricted_project_the_member_isnt_in_is_refused_without_revealing_the_memory_exists(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-doubt-closed", 1301)
    billing = create(signed_out, "Billing")["project_id"]
    payments = create(signed_out, "Payments")["project_id"]
    path = promote_keeping_both(owner.in_project(billing, "billing-api"), TAX)
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(payments)
    restricting = signed_out.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text
    made_up = path.rsplit("/", 1)[0] + "/no-such-memory.md"

    refused = dana.refusal("challenge", path=path, reason="misled")

    assert "is restricted" in refused
    assert refused == dana.refusal("challenge", path=made_up, reason="misled")
    assert owner.in_project(billing, "billing-api").call("read", path=path)["open_challenges"] == []


def test_the_same_memory_with_the_same_reason_joins_the_open_doubt_as_a_plus_one(
    team: Team, owner: Session, dana: Session
) -> None:
    cole = member(team, dana.project or "", "emp-3", "Cole Coder")
    path = promote_keeping_both(owner, TAX)
    first = doubt(dana, path, "contradicts_code", **TAX_LINE)

    second = doubt(cole, path, "contradicts_code", **TAX_LINE, reasoning="tax.py charges twenty percent.")
    third = doubt(dana.as_session("another-session"), path, "contradicts_code", **TAX_LINE)

    assert second == {"challenge_id": first["challenge_id"], "joined": True, "count": 2}
    assert third == {"challenge_id": first["challenge_id"], "joined": True, "count": 3}
    assert len(owner.call("read", path=path)["open_challenges"]) == 1


def test_two_sessions_raising_the_same_doubt_at_once_give_one_challenge_with_two_pieces_of_evidence(
    team: Team, owner: Session, dana: Session, elsewhere: Callable[[Session], Session]
) -> None:
    cole = elsewhere(member(team, dana.project or "", "emp-3", "Cole Coder"))
    path = promote_keeping_both(owner, TAX)

    at_once = [
        dana.call_soon("challenge", path=path, reason="misled", reasoning="Dana's invoices were wrong."),
        cole.call_soon("challenge", path=path, reason="misled", reasoning="Cole's refunds were wrong."),
    ]
    raised = [future.result(timeout=60) for future in at_once]

    assert len({one["challenge_id"] for one in raised}) == 1
    assert sorted(one["joined"] for one in raised) == [False, True]
    assert sorted(one["count"] for one in raised) == [1, 2]
    briefing = added_context(owner.start())
    assert "Dana's invoices were wrong." in briefing and "Cole's refunds were wrong." in briefing


def test_a_different_reason_on_the_same_memory_opens_a_separate_doubt(owner: Session, dana: Session) -> None:
    path = promote_keeping_both(owner, TAX)
    misled = doubt(dana, path, "misled")

    contradicts = doubt(dana, path, "contradicts_code", **TAX_LINE)

    assert contradicts["joined"] is False and contradicts["count"] == 1
    assert contradicts["challenge_id"] != misled["challenge_id"]
    assert len(owner.call("read", path=path)["open_challenges"]) == 2


def test_the_authors_next_briefing_names_the_doubted_memory_the_reason_and_the_evidence(
    team: Team, owner: Session, dana: Session
) -> None:
    cole = member(team, dana.project or "", "emp-3", "Cole Coder")
    path = promote_keeping_both(dana, TAX)
    contradicts = doubt(owner, path, "contradicts_code", **TAX_LINE, reasoning="The code charges twenty percent.")
    doubt(cole, path, "contradicts_code", **TAX_LINE)
    misled = doubt(cole, path, "misled", reasoning="My invoice totals came out wrong.")

    briefing = added_context(dana.start())

    assert f"{TAX['title']} ({path}):" in briefing
    assert f"- Challenge {contradicts['challenge_id']}, a doubt: 2 say it contradicts the code." in briefing
    assert (
        "  - owner-1 quotes billing-api:src/tax.py:42: RATE = Decimal('0.20') — reasoning: The code charges twenty "
        "percent." in briefing
    )
    assert "  - emp-3 quotes billing-api:src/tax.py:42: RATE = Decimal('0.20')" in briefing
    assert f"- Challenge {misled['challenge_id']}, a doubt: 1 says it misled them." in briefing
    assert "  - emp-3 — reasoning: My invoice totals came out wrong." in briefing


def test_the_challenge_tools_description_and_the_skill_say_to_trust_the_code_and_raise_contradicts_code_instead_of_editing(
    dana: Session,
) -> None:
    _, descriptions = dana.on_connecting()
    skill = (REPO_ROOT / "plugin" / "skills" / "shared-memory" / "SKILL.md").read_text(encoding="utf-8")

    for told in (" ".join(text.split()) for text in (descriptions["challenge"], skill)):
        assert "trust the code" in told
        assert "contradicts_code" in told
        assert "never edit the memory to match" in told
