"""Saving a memory names the similar memories within the saving member's reach (#535): their own personal memory in
the project, and the project and team memory they can read. The save itself always lands.

The server here runs the real model for everything but the memories in `CHOSEN`, whose embeddings are picked so each
one's similarity to `NEW` is a number the test chose, not one the model measured."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import SIMILAR_THRESHOLD, Settings
from shared_memory.embeddings import DIMENSIONS, FastEmbedEmbedder
from shared_memory.service import SAVE_SIMILAR_LIMIT
from tests.support import (
    REPO_ROOT,
    Console,
    ConsoleClient,
    FakeGitHub,
    RunningServer,
    Session,
    TestClock,
    add,
    create,
    fresh_database,
    promote_keeping_both,
    signed_in_owner,
)

NEW = "Webhook retries back off exponentially"
# Each title's similarity to NEW: small whole numbers, so every similarity comes out exact.
CHOSEN: dict[str, list[float]] = {
    NEW: [1],
    "Webhook retries wait longer each time": [24, 7],  # 0.96
    "Retried webhooks double their wait": [12, 0, 5],  # 0.923
    "The webhook sender backs off": [4, 0, 0, 3],  # 0.8
    "Webhooks are retried": [1, 0, 0, 0, 1],  # 0.707
    "Webhooks are signed with HMAC": [3, 0, 0, 0, 0, 4],  # 0.6: below the default bar
}
COPY_96, COPY_92, COPY_80, COPY_71, BELOW = list(CHOSEN)[1:]


def chosen(text: str) -> list[float] | None:
    """The embedding chosen for a memory's section, by the memory's title on the section's first line."""
    vector = CHOSEN.get(text.split("\n", 1)[0])
    return None if vector is None else vector + [0.0] * (DIMENSIONS - len(vector))


class ChosenSimilarity(FastEmbedEmbedder):
    """The real model, except that the memories titled in `CHOSEN` get the embeddings chosen for them."""

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [chosen(text) or super().passages([text])[0] for text in texts]


@pytest.fixture(scope="module")
def console(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Console]:
    """This module's own console server, in place of the one every other module shares, for its embedder."""
    with start_blocking_portal() as portal:
        memory = tmp_path_factory.mktemp("similar-memory")
        github = FakeGitHub(portal, Settings("", Path(memory), Path(memory)))
        clock = TestClock()
        settings = Settings(
            database_url=fresh_database("shared_memory_similar_on_save"),
            memory_root=memory,
            model_cache=REPO_ROOT / ".cache" / "fastembed",
            github_client_id="client-id",
            github_client_secret="client-secret",
            github_sign_in_url=github.url,
            github_api_url=github.url,
            rate_limit_on=False,
        )
        embedder = ChosenSimilarity(settings.model_cache)
        server = RunningServer(build_app(settings, clock=clock, embedder=embedder), settings, clock, portal)
        try:
            yield Console(server, github, clock)
        finally:
            server.stop()
            github.stop()


class ATeam:
    """A team with a Billing project, its owner and a member, Dana, each with a session in Billing."""

    def __init__(self, console: Console, client: ConsoleClient, github: str, account: int) -> None:
        self.client = client
        self.owner_anywhere = signed_in_owner(console, client, github, account)
        self.billing = create(client, "Billing")["project_id"]
        self.owner = self.owner_anywhere.in_project(self.billing, "billing-api")
        token = add(client, "emp-2", "Dana Dev", f"dana-{github}")["personal_token"]
        self.dana = Session(console.server, token, self.billing, "billing-api")


def memory(title: str) -> dict[str, str]:
    return {"title": title, "summary": f"{title}.", "type": "gotcha", "body": f"{title}, as the code shows."}


def save(session: Session, title: str) -> dict[str, Any]:
    saved: dict[str, Any] = session.call("remember", **memory(title))
    return saved


def named(saved: dict[str, Any]) -> list[tuple[str, str, float]]:
    """The similar memories a save named: each one's title, level and similarity."""
    return [(each["title"], each["level"], each["similarity"]) for each in saved["similar"]]


def test_a_save_with_a_near_copy_in_reach_names_it_with_level_title_summary_path_and_similarity(
    console: Console, signed_out: ConsoleClient
) -> None:
    team = ATeam(console, signed_out, "olive-similar-one", 1501)
    near_copy = save(team.dana, COPY_96)["path"]

    saved = save(team.dana, NEW)

    assert saved["similar"] == [
        {
            "path": near_copy,
            "level": "personal",
            "title": COPY_96,
            "summary": f"{COPY_96}.",
            "similarity": 0.96,
        }
    ]


def test_a_save_names_near_copies_in_project_and_team_memory(console: Console, signed_out: ConsoleClient) -> None:
    team = ATeam(console, signed_out, "olive-similar-two", 1502)
    in_project = promote_keeping_both(team.owner, memory(COPY_92), "project")
    in_team = promote_keeping_both(team.owner, memory(COPY_80), "team")

    saved = save(team.dana, NEW)

    assert [(each["path"], each["level"]) for each in saved["similar"]] == [(in_project, "project"), (in_team, "company")]


def test_at_most_three_similar_memories_are_named_most_similar_first(
    console: Console, signed_out: ConsoleClient
) -> None:
    team = ATeam(console, signed_out, "olive-similar-three", 1503)
    for title in (COPY_71, COPY_80, COPY_96, BELOW, COPY_92):
        save(team.dana, title)

    saved = save(team.dana, NEW)

    assert named(saved) == [(COPY_96, "personal", 0.96), (COPY_92, "personal", 0.923), (COPY_80, "personal", 0.8)]


def test_another_members_personal_memory_is_never_named(console: Console, signed_out: ConsoleClient) -> None:
    team = ATeam(console, signed_out, "olive-similar-four", 1504)
    save(team.owner, COPY_96)

    saved = save(team.dana, NEW)

    assert "similar" not in saved


def test_a_memory_in_a_project_the_member_cant_reach_is_never_named(
    console: Console, signed_out: ConsoleClient
) -> None:
    team = ATeam(console, signed_out, "olive-similar-five", 1505)
    vault = create(signed_out, "Vault")["project_id"]
    payments = create(signed_out, "Payments")["project_id"]
    restricting = signed_out.post_json(f"/api/projects/{vault}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text
    promote_keeping_both(team.owner_anywhere.in_project(vault, "vault-api"), memory(COPY_96), "project")
    readable = promote_keeping_both(team.owner_anywhere.in_project(payments, "payments-api"), memory(COPY_80), "project")

    saved = save(team.dana, NEW)

    assert [each["path"] for each in saved["similar"]] == [readable], "open projects' memory is in reach; Vault's isn't"


def test_nothing_is_named_and_the_field_is_left_out_when_nothing_passes_the_bar(
    console: Console, signed_out: ConsoleClient
) -> None:
    team = ATeam(console, signed_out, "olive-similar-six", 1506)
    save(team.dana, BELOW)

    saved = save(team.dana, NEW)

    assert "similar" not in saved
    assert saved["level"] == "personal"


def test_the_save_succeeds_whatever_is_similar(console: Console, signed_out: ConsoleClient) -> None:
    team = ATeam(console, signed_out, "olive-similar-seven", 1507)
    first = save(team.dana, NEW)

    again = save(team.dana, NEW)

    assert again["path"] != first["path"]
    assert named(again) == [(NEW, "personal", 1.0)], "an exact copy is named, and still saved"
    assert team.dana.call("read", path=again["path"])["title"] == NEW
    assert not any(each["path"] == again["path"] for each in again["similar"]), "the memory just saved isn't named"


def test_the_save_similar_threshold_reads_its_environment_variable_and_has_a_default() -> None:
    assert Settings.from_env({}).save_similar_threshold == 0.62
    assert Settings.from_env({"SHARED_MEMORY_SAVE_SIMILAR_THRESHOLD": "0.9"}).save_similar_threshold == 0.9


def test_a_save_is_held_to_the_same_similarity_bar_as_promotes_check_named_once() -> None:
    """What a save names is what promoting it would ask about, so both bars are the one constant."""
    settings = Settings.from_env({})

    assert settings.save_similar_threshold == settings.similar_threshold == SIMILAR_THRESHOLD
    assert Settings.save_similar_threshold == Settings.similar_threshold == SIMILAR_THRESHOLD


def test_the_deployment_docs_and_the_compose_file_give_the_save_similar_threshold_its_default() -> None:
    """A limit is named once: the docs and the compose file are static text, so this holds them to the setting's."""
    name, default = "SHARED_MEMORY_SAVE_SIMILAR_THRESHOLD", Settings.from_env({}).save_similar_threshold
    compose = (REPO_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    docs = " ".join((REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8").split())

    assert f"{name}: ${{{name}:-{default:g}}}" in compose
    assert f"`{name}` (default {default:g}" in docs
    assert f"names up to {IN_WORDS[SAVE_SIMILAR_LIMIT]} memories" in docs


# How the static text writes a small count.
IN_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def test_the_tool_description_and_both_skills_name_as_many_similar_memories_as_a_save_does(
    console: Console, signed_out: ConsoleClient
) -> None:
    """A limit is named once: the description and the skills are static text, so this holds them to
    SAVE_SIMILAR_LIMIT."""
    team = ATeam(console, signed_out, "olive-similar-limit", 1511)
    _, descriptions = team.dana.on_connecting()
    up_to = f"up to {IN_WORDS[SAVE_SIMILAR_LIMIT]}"

    assert f"names {up_to} similar memories" in " ".join(descriptions["remember"].split())
    for skill in SKILLS:
        assert f"names {up_to} in `similar`" in skill.read_text(encoding="utf-8"), skill


def test_the_tool_description_says_what_to_do_about_a_similar_memory(console: Console, signed_out: ConsoleClient) -> None:
    team = ATeam(console, signed_out, "olive-similar-eight", 1508)

    _, descriptions = team.dana.on_connecting()

    assert "similar" in descriptions["remember"]
    for choice in ("supersede", "promote", "leave both"):
        assert choice in descriptions["remember"]


SKILLS = [
    REPO_ROOT / "plugin" / "skills" / "shared-memory" / "SKILL.md",
    REPO_ROOT / "src" / "shared_memory" / "skill.md",
]


@pytest.mark.parametrize("skill", SKILLS, ids=["plugin", "server"])
def test_the_skill_says_what_to_do_about_a_similar_memory(skill: Path) -> None:
    text = skill.read_text(encoding="utf-8")
    section = text.split("\n## When a save names similar memories\n")[1].split("\n## ")[0]

    for choice in ("Supersede", "Promote", "Leave both"):
        assert choice in section
