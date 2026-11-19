"""A member's time zone from the console (spec #585): the console reports the zone the browser is set to, which is kept
as the detected one while the member has chosen none, and "Your settings" reads and chooses their own. A member
setting, not a memory write (ADR-0009)."""

from __future__ import annotations

from typing import Any

from shared_memory.console_api import REFUSED_WHILE_READ_ONLY, SAVING
from shared_memory.console_contract import DECLARATIONS
from tests.support import Console, ConsoleClient, Session


def my_time_zone(client: ConsoleClient) -> dict[str, Any]:
    response = client.get("/api/my-time-zone")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def report(client: ConsoleClient, time_zone: str) -> dict[str, Any]:
    response = client.post_json("/api/my-time-zone/detected", {"time_zone": time_zone})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def choose(client: ConsoleClient, time_zone: str | None) -> dict[str, Any]:
    response = client.post_json("/api/my-time-zone", {"time_zone": time_zone})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def signed_in_as_owner(console: Console, client: ConsoleClient, github: str, account: int) -> str:
    """Sign the owner of a new team in; returns the team's code."""
    team, _ = console.a_team(github)
    console.github.as_(account, github)
    client.sign_in()
    return team


def test_a_member_has_no_time_zone_until_one_is_detected_and_can_choose_from_every_zone(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_as_owner(console, signed_out, "olive-zone-one", 5911)

    zone = my_time_zone(signed_out)

    assert zone["chosen"] is None
    assert zone["detected"] is None
    assert "Asia/Kolkata" in zone["time_zones"] and "Europe/Berlin" in zone["time_zones"]
    assert zone["time_zones"] == sorted(zone["time_zones"])


def test_the_reported_browser_zone_is_kept_as_the_detected_one(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_as_owner(console, signed_out, "olive-zone-two", 5912)

    reported = report(signed_out, "Asia/Kolkata")

    assert reported == {"chosen": None, "detected": "Asia/Kolkata"}
    assert my_time_zone(signed_out)["detected"] == "Asia/Kolkata"


def test_the_detected_zone_follows_the_browser_while_nothing_is_chosen(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_as_owner(console, signed_out, "olive-zone-three", 5913)
    report(signed_out, "Asia/Kolkata")

    report(signed_out, "Europe/Berlin")

    assert my_time_zone(signed_out)["detected"] == "Europe/Berlin"


def test_a_member_chooses_their_own_time_zone(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_as_owner(console, signed_out, "olive-zone-four", 5914)
    report(signed_out, "Asia/Kolkata")

    chosen = choose(signed_out, "America/New_York")

    assert chosen == {"chosen": "America/New_York", "detected": "Asia/Kolkata"}
    assert my_time_zone(signed_out)["chosen"] == "America/New_York"


def test_a_chosen_zone_sticks_whatever_the_browser_reports(console: Console, signed_out: ConsoleClient) -> None:
    signed_in_as_owner(console, signed_out, "olive-zone-five", 5915)
    report(signed_out, "Asia/Kolkata")
    choose(signed_out, "America/New_York")

    report(signed_out, "Europe/Berlin")

    zone = my_time_zone(signed_out)
    assert (zone["chosen"], zone["detected"]) == ("America/New_York", "Asia/Kolkata")


def test_detect_automatically_clears_the_choice_and_the_browser_is_followed_again(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_as_owner(console, signed_out, "olive-zone-six", 5916)
    report(signed_out, "Asia/Kolkata")
    choose(signed_out, "America/New_York")

    cleared = choose(signed_out, None)
    report(signed_out, "Europe/Berlin")

    assert cleared == {"chosen": None, "detected": "Asia/Kolkata"}
    assert my_time_zone(signed_out)["detected"] == "Europe/Berlin"


def test_a_name_that_is_no_time_zone_is_refused_and_nothing_changes(
    console: Console, signed_out: ConsoleClient
) -> None:
    signed_in_as_owner(console, signed_out, "olive-zone-seven", 5917)
    report(signed_out, "Asia/Kolkata")
    choose(signed_out, "America/New_York")

    chosen = signed_out.post_json("/api/my-time-zone", {"time_zone": "Mars/Olympus_Mons"})
    detected = signed_out.post_json("/api/my-time-zone/detected", {"time_zone": "UTC+5"})

    assert chosen.status_code == 422
    assert "isn't a time zone" in chosen.json()["message"]
    assert detected.status_code == 422
    zone = my_time_zone(signed_out)
    assert (zone["chosen"], zone["detected"]) == ("America/New_York", "Asia/Kolkata")


def test_a_member_cannot_change_another_members_time_zone(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-zone-eight")
    Session(console.server, owner_token).call("add_member", member_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--team", team, "--member-id", "emp-2", "--github", "dana-zone-eight")
    console.github.as_(5918, "olive-zone-eight")
    signed_out.sign_in()
    dana = console.client()
    try:
        console.github.as_(5919, "dana-zone-eight")
        dana.sign_in()
        choose(dana, "Europe/Berlin")

        choose(signed_out, "Asia/Kolkata")
        signed_out.post_json("/api/my-time-zone", {"time_zone": "America/New_York", "member_id": "emp-2"})

        assert my_time_zone(dana)["chosen"] == "Europe/Berlin"
        assert my_time_zone(signed_out)["chosen"] == "America/New_York"
    finally:
        dana.close()


def test_the_time_zone_calls_ask_for_a_signed_in_member_and_changes_come_from_the_console(
    console: Console, signed_out: ConsoleClient
) -> None:
    assert signed_out.get("/api/my-time-zone").status_code == 401
    assert signed_out.post_json("/api/my-time-zone", {"time_zone": "Asia/Kolkata"}).status_code == 401
    assert signed_out.post_json("/api/my-time-zone/detected", {"time_zone": "Asia/Kolkata"}).status_code == 401
    signed_in_as_owner(console, signed_out, "olive-zone-nine", 5920)

    without_header = signed_out.post("/api/my-time-zone", with_header=False)

    assert without_header.status_code == 403


def test_a_time_zone_is_a_member_setting_not_a_memory_write_so_a_read_only_server_keeps_it() -> None:
    calls = {"my_time_zone", "choose_my_time_zone", "report_my_time_zone"}

    assert calls <= {one.operation_id for one in DECLARATIONS}
    assert not calls & SAVING, "none saves, edits or promotes a memory (ADR-0009)"
    assert not calls & REFUSED_WHILE_READ_ONLY
