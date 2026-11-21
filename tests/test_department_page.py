"""The department page (#636, spec #624): a department's projects, its department memory, and for its department leads
and the company's admins a roll-up of each project's memory, and of department memory's own use.

The roll-up is aggregates only: no member's name, member ID or per-member figure is in the page's answer. A member who
is neither a department lead nor an admin sees the department's projects and memory but no roll-up, and a member
outside a restricted department gets its refusal. Reading the page is no use of any memory and changes nothing
(ADR-0009). Driven through the console's JSON API, with sessions over HTTP making the memory it counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from shared_memory.console_contract import DECLARATIONS
from tests.support import Console, ConsoleClient, Session, add, ask, create, signed_in, signed_in_owner
from tests.test_console_never_writes_memory import watch_for_writes
from tests.test_department_memory import department
from tests.test_level_contradictions import JSON_LOGS, PLAIN_LOGS, contradicting, promoted_now

FLAGS = {
    "title": "Ship behind a flag",
    "summary": "Every change in the department ships behind a feature flag first.",
    "type": "convention",
    "body": "Every change ships dark behind a feature flag, and the flag is removed once it has been on for a week.",
}
TAX = {
    "title": "Sales tax is fifteen percent",
    "summary": "Invoices add fifteen percent sales tax.",
    "type": "convention",
    "body": "Every invoice adds a flat fifteen percent sales tax on the subtotal.",
}
RETRIES = {
    "title": "Webhooks retry three times",
    "summary": "A failed webhook is retried three times with backoff.",
    "type": "gotcha",
    "body": "The provider retries a failed webhook three times, an hour apart, before it gives up.",
}
# Everyone in the company these tests make: none of it may appear in the department page's answer.
MEMBER_NAMES = ("Olive", "Owner", "Dana", "Developer", "Lena", "Mo Member")
MEMBER_IDS = ("E1001", "emp-dana", "emp-lena", "emp-mo")


@dataclass
class APlatformDepartment:
    """Olive, the owner, leads the department Platform with Lena; it holds Billing and Checkout, and one department
    memory no coding agent has used for 61 days. Billing has three project memories: one used today, one read by Dana
    today (her level contradiction against company memory, still waiting), and one unused for 61 days; Dana doubts the
    first. Mo is a member who leads nothing."""

    platform: str
    billing: str
    checkout: str
    department_memory: str
    used: str
    outdated: str
    narrower: str


def a_platform_department(console: Console, client: ConsoleClient, github: str, account: int) -> APlatformDepartment:
    owner = signed_in_owner(console, client, github, account)
    billing = create(client, "Billing")["project_id"]
    checkout = create(client, "Checkout")["project_id"]
    platform = department(client, "Platform", billing, checkout)
    add(client, "emp-lena", "Lena Lead", f"lena-{github}")
    appointed = client.post_json(f"/api/departments/{platform}/leads", {"member_id": "emp-lena"})
    assert appointed.status_code == 200, appointed.text
    add(client, "emp-mo", "Mo Member", f"mo-{github}")
    olive = owner.in_project(billing, "app")
    company = promoted_now(olive, JSON_LOGS, "company")
    dana = Session(console.server, add(client, "emp-dana", "Dana Developer")["personal_token"], billing, "app")
    raised = contradicting(dana, PLAIN_LOGS, company)
    assert "level_contradiction" in raised, raised
    department_memory = promoted_now(olive, FLAGS, "department")
    used = promoted_now(olive, TAX, "project")
    outdated = promoted_now(olive, RETRIES, "project")
    dana.call("challenge", path=used, reason="misled")
    console.clock.advance(days=61)
    olive.call("read", path=used)
    dana.call("read", path=raised["path"])
    console.github.as_(account, github)
    client.sign_in()
    return APlatformDepartment(platform, billing, checkout, department_memory, used, outdated, raised["path"])


def page(client: ConsoleClient, department_id: str) -> dict[str, Any]:
    return ask(client, f"/api/departments/{department_id}")


def counts(answer: dict[str, Any], project_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(one for one in answer["roll_up"]["projects"] if one["project_id"] == project_id)
    counted: dict[str, Any] = found["counts"]
    return counted


BILLING = {"memories": 3, "possibly_outdated": 1, "used": 2, "level_contradictions": 1, "challenges": 1}
NOTHING = {"memories": 0, "possibly_outdated": 0, "used": 0, "level_contradictions": 0, "challenges": 0}
DEPARTMENT_MEMORY = {"memories": 1, "possibly_outdated": 1, "used": 0, "level_contradictions": 0, "challenges": 0}


def test_a_department_lead_sees_each_projects_counts_and_department_memorys_use(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = a_platform_department(console, signed_out, "olive-dept-page-lead", 6361)
    lena = signed_in(console, "lena-olive-dept-page-lead", 6362)

    answer = page(lena, it.platform)

    assert (answer["department_id"], answer["name"], answer["you_lead"]) == (it.platform, "Platform", True)
    assert [one["name"] for one in answer["projects"]] == ["Billing", "Checkout"]
    assert [one["path"] for one in answer["memory"]] == [it.department_memory]
    assert answer["memory"][0]["title"] == FLAGS["title"]
    roll_up = answer["roll_up"]
    assert (roll_up["window_days"], roll_up["outdated_after_days"]) == (30, 60)
    assert [one["name"] for one in roll_up["projects"]] == ["Billing", "Checkout"]
    assert counts(answer, it.billing) == BILLING
    assert counts(answer, it.checkout) == NOTHING
    assert roll_up["department_memory"] == DEPARTMENT_MEMORY
    lena.close()


def test_an_admin_sees_the_same_roll_up(console: Console, signed_out: ConsoleClient) -> None:
    it = a_platform_department(console, signed_out, "olive-dept-page-admin", 6363)
    left = signed_out.post(f"/api/departments/{it.platform}/leads/E1001/remove")
    assert left.status_code == 200, left.text

    answer = page(signed_out, it.platform)

    assert answer["you_lead"] is False
    assert counts(answer, it.billing) == BILLING
    assert answer["roll_up"]["department_memory"] == DEPARTMENT_MEMORY


def test_no_member_name_or_member_id_is_in_the_answer(console: Console, signed_out: ConsoleClient) -> None:
    it = a_platform_department(console, signed_out, "olive-dept-page-names", 6364)

    answer = signed_out.get(f"/api/departments/{it.platform}")

    assert answer.status_code == 200, answer.text
    assert answer.json()["roll_up"] is not None
    assert not [name for name in MEMBER_NAMES if name in answer.text]
    assert not [member_id for member_id in MEMBER_IDS if member_id in answer.text]
    assert "author" not in answer.text and "member" not in answer.text


def test_a_member_who_leads_nothing_sees_the_projects_and_memory_but_no_roll_up(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = a_platform_department(console, signed_out, "olive-dept-page-member", 6365)
    mo = signed_in(console, "mo-olive-dept-page-member", 6366)

    answer = page(mo, it.platform)

    assert answer["you_lead"] is False
    assert [one["project_id"] for one in answer["projects"]] == [it.billing, it.checkout]
    assert [one["path"] for one in answer["memory"]] == [it.department_memory]
    assert answer["roll_up"] is None
    mo.close()


def test_a_member_outside_a_restricted_department_is_refused_and_one_on_its_list_reads_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = a_platform_department(console, signed_out, "olive-dept-page-closed", 6367)
    closed = signed_out.post_json(f"/api/departments/{it.platform}/restrict", {"restricted": True})
    assert closed.status_code == 200, closed.text
    mo = signed_in(console, "mo-olive-dept-page-closed", 6368)

    refused = mo.get(f"/api/departments/{it.platform}")
    let_in = signed_out.post_json(f"/api/departments/{it.platform}/access", {"member_id": "emp-mo"})
    reached = mo.get(f"/api/departments/{it.platform}")

    assert refused.status_code == 403
    assert "is restricted" in refused.json()["message"]
    assert "Ship behind a flag" not in refused.text and "Billing" not in refused.text
    assert let_in.status_code == 200, let_in.text
    assert reached.status_code == 200, reached.text
    assert reached.json()["roll_up"] is None
    mo.close()


def test_a_department_that_doesnt_exist_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_owner(console, signed_out, "olive-dept-page-missing", 6369)

    answer = signed_out.get("/api/departments/no-such-department")

    assert answer.status_code == 403
    assert "'no-such-department' is not a department in your company." in answer.json()["message"]


def test_reading_the_department_page_changes_nothing(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    it = a_platform_department(console, signed_out, "olive-dept-page-unchanged", 6370)
    reached = watch_for_writes(monkeypatch)

    first = page(signed_out, it.platform)
    again = page(signed_out, it.platform)

    [declared] = [one for one in DECLARATIONS if one.path == "/departments/{department_id}"]
    assert (declared.method, declared.changes) == ("GET", False)
    assert reached == []
    # Reading it is no use of a memory: the outdated department memory is still outdated the second time.
    assert first == again
    assert again["roll_up"]["department_memory"]["possibly_outdated"] == 1
