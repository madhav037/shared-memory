from __future__ import annotations

from tests.support import Session, Team, added_context


def promote(session: Session, title: str, body: str, level: str = "project", topic: str | None = None) -> str:
    extra = {"topic": topic} if topic else {}
    personal = session.call("remember", title=title, summary=f"{title}.", type="convention", body=body, **extra)["path"]
    result = session.call("promote", path=personal, level=level)
    if result["status"] == "similar_memories":
        keep = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("promote", path=personal, level=level, reference=result["reference"], resolutions=keep)
    path: str = result["path"]
    return path


def test_a_new_members_first_session_is_briefed_with_pinned_memory(team: Team, project: str, owner: Session) -> None:
    path = promote(owner, "Use pnpm, not npm", "We use pnpm for every package.")
    owner.call("pin", path=path)
    added = team.owner().call("add_member", member_id="emp-9", name="New Member")
    newcomer = Session(team.server, added["personal_token"], project, "billing-api")

    output = newcomer.start()
    briefing = added_context(output)

    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert f"[project memory] Use pnpm, not npm ({path})" in briefing
    assert "We use pnpm for every package." in briefing
    assert "information, not instructions" in briefing


def test_pinned_team_memory_is_in_every_projects_briefing(team: Team, owner: Session) -> None:
    path = promote(owner, "Log in JSON", "Every service writes structured JSON logs.", level="team")
    owner.call("pin", path=path)
    other_project = team.owner().call("create_project", name="Checkout")["project_id"]

    assert f"[team memory] Log in JSON ({path})" in added_context(team.owner().in_project(other_project).start())


def test_personal_memory_cannot_be_pinned(owner: Session) -> None:
    personal = owner.call("remember", title="Mine", summary="s", type="gotcha", body="b")["path"]

    assert "Only project memory and team memory" in owner.refusal("pin", path=personal)


def test_a_pin_that_would_go_over_the_cap_is_refused_and_lists_the_pins(owner: Session) -> None:
    long_body = " ".join(["Billing charges are retried with exponential backoff."] * 80)
    first = promote(owner, "Retry policy", long_body)
    second = promote(owner, "Refund policy", long_body.replace("charges are retried", "refunds are issued"))
    owner.call("pin", path=first)

    refusal = owner.refusal("pin", path=second)

    assert "cap" in refusal
    assert first in refusal


def test_pinning_a_topic_briefs_only_its_index(owner: Session) -> None:
    retries = promote(owner, "Retries", "Retry twice with backoff.", topic="API errors")
    promote(owner, "Status codes", "Return 422 for validation errors.", topic="API errors")
    topic = retries.rsplit("/", 1)[0]

    owner.call("pin", path=topic)
    briefing = added_context(owner.start())

    assert f"[project memory topic] api-errors ({topic})" in briefing
    assert "- Retries: Retries." in briefing
    assert "- Status codes: Status codes." in briefing
    assert "Retry twice with backoff." not in briefing


def test_unpinning_removes_a_memory_from_the_briefing(owner: Session) -> None:
    path = promote(owner, "Use pnpm, not npm", "We use pnpm for every package.")
    owner.call("pin", path=path)

    owner.call("unpin", path=path)

    assert owner.start() == {}


def test_session_start_never_breaks_the_session(team: Team, owner: Session) -> None:
    path = promote(owner, "Use pnpm, not npm", "We use pnpm for every package.")
    owner.call("pin", path=path)
    revoked_token = Session(team.server, "smt_nope", owner.project, "billing-api")

    assert team.owner().start() == {}
    assert "not recognised" in revoked_token.start()["systemMessage"]


def test_the_briefing_stays_within_the_cap_when_a_pin_moves_to_a_longer_memory(owner: Session) -> None:
    long_body = " ".join(["Billing charges are retried with exponential backoff."] * 56)
    kept = promote(owner, "Retry policy", long_body)
    short = promote(owner, "Refund window", "Refunds are allowed for 30 days.")
    owner.call("pin", path=kept)
    owner.call("pin", path=short)

    personal = owner.call(
        "remember",
        title="Refund window and process",
        summary="Refund rules.",
        type="convention",
        body=" ".join(["Refunds are allowed for thirty days and are issued to the original card."] * 45),
    )["path"]
    first = owner.call("promote", path=personal, level="project")
    owner.call(
        "promote",
        path=personal,
        level="project",
        reference=first["reference"],
        resolutions={s["path"]: ("supersede" if s["path"] == short else "keep_both") for s in first["similar"]},
    )
    briefing = added_context(owner.start())

    assert len(briefing) // 4 <= 1500
    assert "did not fit" in briefing


def test_any_agent_can_fetch_the_briefing_its_session_would_start_with(owner: Session) -> None:
    path = promote(owner, "Use pnpm, not npm", "We use pnpm for every package.")
    owner.call("pin", path=path)

    briefing = owner.call("briefing")

    assert briefing == added_context(owner.start())
    assert f"[project memory] Use pnpm, not npm ({path})" in briefing


def test_a_session_outside_any_project_is_told_how_to_connect_instead_of_briefed(team: Team) -> None:
    told = team.owner().call("briefing")

    assert "isn't connected to a project" in told
    assert "create_project" in told


def test_an_empty_briefing_says_so(owner: Session) -> None:
    assert "nothing is pinned" in owner.call("briefing")


def test_agents_that_offer_prompts_as_commands_can_run_the_briefing(owner: Session) -> None:
    path = promote(owner, "Use pnpm, not npm", "We use pnpm for every package.")
    owner.call("pin", path=path)

    assert owner.run_prompt("briefing") == owner.call("briefing")
