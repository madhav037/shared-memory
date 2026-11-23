"""Text a member writes is matched in time that grows with its length, never with its square or worse: a crafted
reason, heading, patch or tied file is answered promptly. Driven through the Session driver over HTTP."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from tests.support import WORKING_FOLDER, Company, Session, ToolRefused, promote_keeping_both

# What each input below took before it was fixed: minutes at least. Linear matching answers in well under a second.
PROMPTLY = 5.0


def answered_promptly(call: Callable[[], Any]) -> None:
    started = time.monotonic()
    try:
        call()
    except ToolRefused:
        pass
    assert time.monotonic() - started < PROMPTLY


@pytest.fixture
def member(company: Company) -> Session:
    project = company.owner().call("create_project", name="Billing")["project_id"]
    return company.owner().in_project(project, "billing-api")


def test_a_doubts_reasoning_of_dotted_words_is_answered_promptly(member: Session) -> None:
    path = promote_keeping_both(
        member, {"title": "Tax is fifteen percent", "summary": "Invoices add tax.", "type": "convention", "body": "b"}
    )

    answered_promptly(lambda: member.call("challenge", path=path, reason="misled", reasoning="a." * 100_000))


def test_a_heading_padded_with_spaces_is_saved_promptly(member: Session) -> None:
    body = "Intro.\n#" + " " * 11_000 + "x\nMore."

    answered_promptly(lambda: member.call("remember", title="Padded", summary="s", type="convention", body=body))


def test_a_workaround_padded_with_spaces_is_saved_promptly(member: Session) -> None:
    body = "It breaks.\nWorkaround:" + " " * 11_000 + "x"

    answered_promptly(lambda: member.call("save_known_issue", title="Padded", summary="s", body=body))


def test_a_patch_naming_a_file_padded_with_spaces_is_answered_promptly(member: Session) -> None:
    payload = {
        "session_id": member.identifier,
        "cwd": WORKING_FOLDER,
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Update File: a" + " " * 300_000 + "x"},
    }

    answered_promptly(lambda: member.hook_payload("before-edit", payload))


def test_a_tied_glob_of_many_wildcards_is_matched_promptly(member: Session) -> None:
    member.call(
        "remember",
        title="Nested",
        summary="s",
        type="convention",
        body="b",
        tied_files=["billing-api:" + "**a" * 9 + "**b"],
    )

    answered_promptly(lambda: member.call("tied_memories", file="billing-api:" + "a" * 400))


def test_a_long_code_reference_with_no_line_is_refused_promptly(member: Session) -> None:
    path = promote_keeping_both(
        member, {"title": "Tax is twenty percent", "summary": "Invoices add tax.", "type": "convention", "body": "b"}
    )

    answered_promptly(
        lambda: member.call(
            "challenge", path=path, reason="contradicts_code", code_reference="r:" + "a" * 100_000, quoted_line="x"
        )
    )
