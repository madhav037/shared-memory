"""A request that will be refused costs little: a console body is weighed before it is read, and an edit that may not
be made embeds nothing. Driven through the Session driver and the console over HTTP."""

from __future__ import annotations

from typing import Any

import pytest

from shared_memory.index import SearchIndex
from shared_memory.memory import Memory
from tests.support import Company, ConsoleClient, Session, member


def test_a_console_body_past_the_limit_is_refused_unread(signed_out: ConsoleClient) -> None:
    answer = signed_out.post_json("/api/projects/billing/cards", {"title": "t", "labels": [1] * 400_000})

    assert answer.status_code == 413


def test_a_console_body_with_many_mistakes_names_only_a_few(signed_out: ConsoleClient) -> None:
    answer = signed_out.post_json("/api/projects/billing/cards", {"title": "t", "labels": [1] * 20_000})

    assert answer.status_code == 422
    assert len(answer.text) < 300


def test_an_edit_of_someone_elses_memory_embeds_nothing(company: Company, monkeypatch: pytest.MonkeyPatch) -> None:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    owner = company.owner().in_project(project, "billing-api")
    saved = owner.call("remember", title="Retry twice", summary="s", type="convention", body="b")
    dana: Session = member(company, project, "emp-2", "Dana Dev")
    prepared: list[Memory] = []
    original = SearchIndex.prepare

    def watched(self: SearchIndex, company_code: str, memory: Memory, *args: Any) -> None:
        prepared.append(memory)
        original(self, company_code, memory, *args)

    monkeypatch.setattr(SearchIndex, "prepare", watched)

    refusal = dana.refusal("edit_memory", path=saved["path"], body="words " * 5_000)

    assert "your own" in refusal
    assert prepared == []
