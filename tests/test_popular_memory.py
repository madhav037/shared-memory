"""Popular memory (#538, spec #502): a personal memory enough other members' sessions have read within the window, each
member counting once, is named in its author's next briefing, pointing at promote. Driven through the Session driver
over HTTP."""

from __future__ import annotations

from typing import Any

from shared_memory.config import POPULAR_MEMBERS, POPULAR_REPROMPT_FACTOR, POPULAR_WINDOW_DAYS, Settings
from tests.support import REPO_ROOT, Session, Team, member

RETRIES = {
    "title": "The payment relay retries for a day",
    "summary": "A failed payment webhook is retried for twenty-four hours.",
    "type": "gotcha",
    "body": "The payment relay retries a failed webhook delivery with backoff for twenty-four hours before giving up.",
}


def remembered(session: Session, memory: dict[str, Any] = RETRIES) -> str:
    path: str = session.call("remember", **memory)["path"]
    return path


def read_by(path: str, *readers: Session) -> None:
    for reader in readers:
        reader.call("read", path=path)


def briefing(session: Session) -> str:
    text: str = session.call("briefing")
    return text


def named(session: Session, path: str) -> bool:
    return f"({path}) was read by" in briefing(session)


def test_a_personal_memory_two_other_members_read_is_named_once_in_its_authors_next_briefing(
    owner: Session, dana: Session, cole: Session
) -> None:
    path = remembered(dana)
    read_by(path, owner, cole)

    first = briefing(dana)
    again = briefing(dana)

    assert first.count(path) == 1, first
    assert f"({path}) was read by 2 other members' sessions in the last 30 days" in first
    assert "promote" in first
    assert path not in again


def test_the_authors_own_reads_dont_count(dana: Session, cole: Session) -> None:
    path = remembered(dana)
    read_by(path, dana, dana, cole)

    assert not named(dana, path)


def test_one_other_member_alone_however_often_is_not_enough(dana: Session, cole: Session) -> None:
    path = remembered(dana)
    read_by(path, *[cole] * 5)

    assert not named(dana, path)


def test_the_memory_is_named_again_only_once_its_readers_have_doubled(
    team: Team, project: str, owner: Session, dana: Session, cole: Session
) -> None:
    erin = member(team, project, "emp-4", "Erin Engineer")
    finn = member(team, project, "emp-5", "Finn Fixer")
    path = remembered(dana)
    read_by(path, owner, cole)
    assert named(dana, path)

    read_by(path, erin)
    at_three = briefing(dana)
    read_by(path, finn)
    at_four = briefing(dana)

    assert path not in at_three
    assert f"({path}) was read by 4 other members' sessions" in at_four


def test_reads_older_than_the_window_stop_counting(team: Team, owner: Session, dana: Session, cole: Session) -> None:
    path = remembered(dana)
    read_by(path, owner)
    team.server.clock.advance(days=31)
    read_by(path, cole)

    assert not named(dana, path)


def test_a_promoted_memory_is_never_named(owner: Session, dana: Session, cole: Session) -> None:
    path = remembered(dana)
    read_by(path, owner, cole)

    first = dana.call("promote", path=path, level="project")
    if first["status"] == "similar_memories":
        first = dana.call(
            "promote",
            path=path,
            level="project",
            reference=first["reference"],
            resolutions={similar["path"]: "keep_both" for similar in first["similar"]},
        )
    assert first["status"] == "promoted", first

    assert not named(dana, path)


def test_a_deleted_memory_is_never_named(owner: Session, dana: Session, cole: Session) -> None:
    path = remembered(dana)
    read_by(path, owner, cole)
    dana.call("delete_memory", path=path)

    assert not named(dana, path)


def test_a_memory_in_doubt_is_never_named(owner: Session, dana: Session, cole: Session) -> None:
    path = remembered(dana)
    read_by(path, owner, cole)
    cole.call("challenge", path=path, reason="misled", reasoning="The relay gave up after an hour.")

    assert not named(dana, path)


def test_another_members_briefing_never_names_it(owner: Session, dana: Session, cole: Session) -> None:
    path = remembered(dana)
    read_by(path, owner, cole)

    assert not named(cole, path)
    assert named(dana, path)


def test_the_popular_settings_read_their_environment_variables_and_have_defaults() -> None:
    defaults = Settings.from_env({})
    assert (defaults.popular_members, defaults.popular_window_days, defaults.popular_reprompt_factor) == (2, 30, 2)
    assert (POPULAR_MEMBERS, POPULAR_WINDOW_DAYS, POPULAR_REPROMPT_FACTOR) == (2, 30, 2), "as the ticket says"

    tuned = Settings.from_env(
        {
            "SHARED_MEMORY_POPULAR_MEMBERS": "3",
            "SHARED_MEMORY_POPULAR_WINDOW_DAYS": "14",
            "SHARED_MEMORY_POPULAR_REPROMPT_FACTOR": "1.5",
        }
    )
    assert (tuned.popular_members, tuned.popular_window_days, tuned.popular_reprompt_factor) == (3, 14, 1.5)


def test_the_deployment_docs_and_the_compose_file_give_the_popular_settings_their_defaults() -> None:
    compose = (REPO_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    docs = " ".join((REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8").split())
    defaults = Settings.from_env({})
    for name, default in [
        ("SHARED_MEMORY_POPULAR_MEMBERS", defaults.popular_members),
        ("SHARED_MEMORY_POPULAR_WINDOW_DAYS", defaults.popular_window_days),
        ("SHARED_MEMORY_POPULAR_REPROMPT_FACTOR", defaults.popular_reprompt_factor),
    ]:
        assert f"{name}: ${{{name}:-{default:g}}}" in compose
        assert f"`{name}` (default {default:g}" in docs
