"""Onboarding: the steps a session is given to import a member's existing setup, and promote naming the member who
wrote an imported memory as its author."""

from __future__ import annotations

from typing import Any

from tests.support import (
    NPM,
    PNPM,
    REPO_ROOT,
    Console,
    ConsoleClient,
    Session,
    Company,
    added_context,
    promote_now,
    signed_in_owner,
)

CENTS = {
    "title": "Money amounts",
    "summary": "Money is integer cents.",
    "type": "convention",
    "body": "All money amounts are stored as integer cents, never floats.",
}
SOURCE = "billing-api:CLAUDE.md"


def imported(session: Session, memory: dict[str, str] = CENTS) -> str:
    """A memory the session's member has imported, still in their personal memory."""
    path: str = session.call("remember", **memory)["path"]
    return path


def promoted_for(session: Session, author: str, memory: dict[str, str] = CENTS, level: str = "project") -> str:
    result = session.call("promote", path=imported(session, memory), level=level, author=author, imported_from=SOURCE)
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


# The steps, and where a session finds them


def test_the_onboarding_steps_are_served_as_a_tool_and_as_a_prompt(owner: Session) -> None:
    steps = owner.call("onboard")

    assert owner.run_prompt("onboard") == steps
    for needed in ("git blame", "remember", "promote", "author", "imported_from", "secret", "ten"):
        assert needed in steps, needed


def test_onboarding_needs_a_connected_repository(company: Company) -> None:
    assert "isn't connected to a project" in company.owner().refusal("onboard")
    assert "isn't connected to a project" in company.owner().run_prompt("onboard")


def test_an_agent_learns_on_connecting_that_onboarding_starts_only_when_the_member_asks(company: Company) -> None:
    instructions, tools = company.owner().on_connecting()

    assert "onboard" in instructions
    assert "only when the member asks" in tools["onboard"]


def test_the_skills_point_at_the_served_steps_instead_of_repeating_them(company: Company) -> None:
    created = company.owner().call("create_project", name="Billing", repository="billing-api")
    every_agents = next(f for f in created["files"] if f["path"] == ".agents/skills/shared-memory/SKILL.md")
    claude_codes = (REPO_ROOT / "plugin" / "skills" / "onboard" / "SKILL.md").read_text(encoding="utf-8")

    for skill in (every_agents["contents"], claude_codes):
        assert "`onboard`" in skill
        assert "git blame" not in skill


# Where a member meets onboarding: the briefing of a project with no project memory


def test_the_briefing_in_an_empty_project_with_no_imports_offers_onboarding(owner: Session) -> None:
    told = added_context(owner.start())

    assert "[onboarding]" in told
    assert "only if the member asks" in told


def test_the_onboarding_line_goes_once_the_project_has_memory(owner: Session) -> None:
    promote_now(owner, PNPM)

    assert "[onboarding]" not in added_context(owner.start())


def test_the_onboarding_line_goes_once_the_member_has_imported_from_the_repository(
    owner: Session, dana: Session
) -> None:
    path = promoted_for(owner, "emp-2")
    dana.call("retire", path=path)

    assert "[onboarding]" not in added_context(owner.start())


# Promote naming the author of an imported memory


def test_a_member_named_as_author_becomes_the_author_and_the_importer_and_source_are_recorded(
    owner: Session, dana: Session
) -> None:
    memory = owner.call("read", path=promoted_for(owner, "emp-2"))

    assert (memory["level"], memory["author"]) == ("project", "emp-2")
    assert (memory["imported_by"], memory["imported_from"]) == ("owner-1", SOURCE)


def test_the_author_can_be_named_by_their_github_username(company: Company, owner: Session) -> None:
    company.owner().call("add_member", member_id="emp-7", name="Gita Hub", github="Gita-Hub")

    memory = owner.call("read", path=promoted_for(owner, "@gita-hub", level="company"))

    assert (memory["level"], memory["author"], memory["imported_by"]) == ("company", "emp-7", "owner-1")


def test_someone_who_is_not_a_member_cannot_be_named_as_author(company: Company, owner: Session, dana: Session) -> None:
    personal = imported(owner)
    company.owner().call("remove_member", member_id="emp-2")

    unknown = owner.refusal("promote", path=personal, level="project", author="emp-99", imported_from=SOURCE)
    no_account = owner.refusal("promote", path=personal, level="project", author="@nobody", imported_from=SOURCE)
    removed = owner.refusal("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)

    assert "No member with member ID 'emp-99'" in unknown
    assert "@nobody" in no_account and "without author" in no_account
    assert "No member with member ID 'emp-2'" in removed
    assert owner.call("read", path=personal)["level"] == "personal"


def test_a_member_outside_a_restricted_project_cannot_be_named_as_author(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards-closed", 7801)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")
    closed = signed_out.post_json(f"/api/projects/{project}/restrict", {"restricted": True})
    assert closed.status_code == 200, closed.text
    in_project = owner.in_project(project, "billing-api")

    for level in ("project", "company"):
        refusal = in_project.refusal(
            "promote", path=imported(in_project), level=level, author="emp-2", imported_from=SOURCE
        )
        assert "can't reach project" in refusal, level


def test_an_author_is_named_only_with_the_source_and_never_oneself(owner: Session, dana: Session) -> None:
    personal = imported(owner)

    assert "imported_from" in owner.refusal("promote", path=personal, level="project", author="emp-2")
    assert "author" in owner.refusal("promote", path=personal, level="project", imported_from=SOURCE)
    assert "already its author" in owner.refusal(
        "promote", path=personal, level="project", author="owner-1", imported_from=SOURCE
    )
    assert "repository:path" in owner.refusal(
        "promote", path=personal, level="project", author="emp-2", imported_from="CLAUDE.md\nand more"
    )


OUTSIDE_SOURCES = (
    "wiki:Payments/Refund rules",
    "ticket:PAY-412",
    "pr-comment:billing-api#88",
    "commit:billing-api@3f9c2ab",
    "interview:Billing with emp-2",
)


def test_promote_accepts_an_outside_source_a_commit_or_an_interview_as_where_an_import_came_from(
    owner: Session, dana: Session
) -> None:
    for number, source in enumerate(OUTSIDE_SOURCES):
        memory = {**CENTS, "title": f"Money amounts {number}", "body": f"{CENTS['body']} Rule {number}."}
        personal = imported(owner, memory)
        result = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=source)
        if result["status"] == "similar_memories":
            keep_both = {one["path"]: "keep_both" for one in result["similar"]}
            result = owner.call(
                "promote", path=personal, level="project", reference=result["reference"], resolutions=keep_both
            )
        assert result["status"] == "promoted", (source, result)

        promoted = owner.call("read", path=result["path"])
        assert (promoted["author"], promoted["imported_by"], promoted["imported_from"]) == (
            "emp-2",
            "owner-1",
            source,
        ), source


def test_the_audit_log_shows_the_importer_and_an_outside_source(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards-wiki", 7805)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")
    in_project = owner.in_project(project, "billing-api")

    result = in_project.call(
        "promote", path=imported(in_project), level="project", author="emp-2", imported_from="ticket:PAY-412"
    )
    assert result["status"] == "promoted", result

    (event,) = signed_out.get(f"/api/audit?project={project}&kind=memory_promoted").json()["events"]
    detail: dict[str, Any] = event["detail"]
    assert (detail["author"], detail["imported_by"], detail["imported_from"]) == ("emp-2", "E1001", "ticket:PAY-412")


def test_a_malformed_source_is_refused_naming_the_accepted_forms(owner: Session, dana: Session) -> None:
    personal = imported(owner)

    for malformed in ("CLAUDE.md", "ticket:", "wiki:   ", "commit:billing-api", "commit:@3f9c2ab", "notes/x.md"):
        refusal = owner.refusal("promote", path=personal, level="project", author="emp-2", imported_from=malformed)
        for form in ("repository:path", "wiki:", "ticket:", "pr-comment:", "commit:repository@", "interview:"):
            assert form in refusal, (malformed, form)
    assert owner.call("read", path=personal)["level"] == "personal"


def test_the_promote_tool_names_every_form_of_source(company: Company) -> None:
    _, tools = company.owner().on_connecting()

    for form in ("repository:path", "wiki:", "ticket:", "pr-comment:", "commit:", "interview:"):
        assert form in tools["promote"], form


def test_the_author_is_told_in_their_next_briefing(owner: Session, dana: Session) -> None:
    path = promoted_for(owner, "emp-2")

    told = added_context(dana.start())

    assert "owner-1 promoted a memory in your name" in told
    assert path in told and SOURCE in told and "Money amounts" in told
    assert "in your name" not in added_context(dana.start())
    assert "in your name" not in added_context(owner.start())


def test_the_named_author_retires_the_memory_as_any_author_does(owner: Session, dana: Session) -> None:
    path = promoted_for(owner, "emp-2")

    by_the_importer = owner.call("retire", path=path)
    by_the_author = dana.call("retire", path=path)

    assert by_the_importer["status"] == "challenge_raised"
    assert by_the_author == {"status": "retired", "path": path}


def test_the_similar_memory_check_still_runs_and_the_author_holds_through_it(owner: Session, dana: Session) -> None:
    existing = promote_now(owner, NPM)
    personal = imported(owner, PNPM)

    first = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)
    while_it_waits = owner.call("read", path=personal)
    result = owner.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "keep_both"}
    )

    assert first["status"] == "similar_memories"
    assert (while_it_waits["level"], while_it_waits["author"]) == ("personal", "owner-1")
    memory = owner.call("read", path=result["path"])
    assert (memory["author"], memory["imported_by"], memory["imported_from"]) == ("emp-2", "owner-1", SOURCE)


def test_the_author_holds_when_the_promotion_waits_on_a_challenge(owner: Session, dana: Session, cole: Session) -> None:
    existing = promote_now(cole, NPM)
    personal = imported(owner, PNPM)
    first = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)
    raised = owner.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "supersede"}
    )

    accepted = cole.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    memory = owner.call("read", path=accepted["path"])
    assert (memory["author"], memory["imported_by"], memory["replaces"]) == ("emp-2", "owner-1", existing)
    assert "owner-1 promoted a memory in your name" in added_context(dana.start())


def test_a_cancelled_promotion_leaves_no_author_behind_for_the_next_one(owner: Session, dana: Session) -> None:
    existing = promote_now(owner, NPM)
    personal = imported(owner, PNPM)
    first = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=SOURCE)
    owner.call("promote", path=personal, level="project", reference=first["reference"], resolutions={existing: "cancel"})

    again = owner.call("promote", path=personal, level="project")
    result = owner.call(
        "promote", path=personal, level="project", reference=again["reference"], resolutions={existing: "keep_both"}
    )

    memory = owner.call("read", path=result["path"])
    assert (memory["author"], memory["imported_by"], memory["imported_from"]) == ("owner-1", None, None)


def test_the_audit_log_shows_the_author_and_the_importer(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards", 7802)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")
    in_project = owner.in_project(project, "billing-api")

    path = promoted_for(in_project, "emp-2")

    response = signed_out.get(f"/api/audit?project={project}&kind=memory_promoted")
    assert response.status_code == 200, response.text
    (event,) = response.json()["events"]
    detail: dict[str, Any] = event["detail"]
    assert (event["actor"], event["target"]) == ("E1001", path)
    assert (detail["author"], detail["imported_by"], detail["imported_from"]) == ("emp-2", "E1001", SOURCE)


def test_the_console_still_reads_an_imported_memory(console: Console, signed_out: ConsoleClient) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards-reads", 7803)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")

    path = promoted_for(owner.in_project(project, "billing-api"), "emp-2")

    response = signed_out.get(f"/api/memory?path={path}")
    assert response.status_code == 200, response.text
    assert (response.json()["author"], response.json()["author_name"]) == ("emp-2", "Dana Dev")
    assert "imported_by: E1001" in response.json()["source"]


def test_the_console_names_an_imported_memorys_importer_and_source(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-onboards-names", 7804)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.call("add_member", member_id="emp-2", name="Dana Dev")
    in_project = owner.in_project(project, "billing-api")

    path = promoted_for(in_project, "emp-2")
    own = promote_now(in_project, PNPM)

    detail = signed_out.get(f"/api/memory?path={path}").json()
    assert (detail["author"], detail["imported_by"], detail["imported_from"]) == ("emp-2", "E1001", SOURCE)
    plain = signed_out.get(f"/api/memory?path={own}").json()
    assert (plain["imported_by"], plain["imported_from"]) == (None, None)


# Onboarding maps repository documents onto foundations


def test_the_steps_map_documents_onto_foundations_and_ask_before_replacing_a_file_with_a_pointer(owner: Session) -> None:
    steps = owner.call("onboard")
    assert "foundation" in steps
    assert "Ask the member first" in steps
    assert steps.index("Map repository documents onto foundations") < steps.index("Promote what the member approved")
    assert steps.index("Promote what the member approved") < steps.index("Replace imported files with pointers")


# The steps cover what a brownfield company has (#619)


def test_the_steps_have_the_member_choose_this_runs_sources_at_the_start_and_say_what_it_costs(owner: Session) -> None:
    steps = owner.call("onboard")

    assert "Choose this run's sources" in steps
    assert steps.index("Choose this run's sources") < steps.index("Cut each source into proposals")
    assert "own tokens" in steps


def test_the_steps_cover_git_history_a_code_scan_and_outside_sources_with_how_to_reach_them(owner: Session) -> None:
    steps = owner.call("onboard")

    for needed in ("**Git history**", "revert", "**A scan of the code**", "utilities", "**Outside sources**"):
        assert needed in steps, needed
    for reach in ("gh", "glab", "MCP server", "exported folder", "couldn't reach"):
        assert reach in steps, reach
    for form in ("commit:repository@revision", "wiki:<page>", "ticket:<reference>", "pr-comment:<reference>"):
        assert form in steps, form


def test_the_steps_walk_several_checkouts_into_one_list_of_proposals(owner: Session) -> None:
    steps = owner.call("onboard")

    assert "several checkouts" in steps
    assert "one list of proposals" in steps


def test_the_steps_collapse_identical_rules_and_show_disagreeing_variants_side_by_side(owner: Session) -> None:
    steps = owner.call("onboard")

    assert "becomes one proposal" in steps
    assert "`company` level" in steps
    assert "side by side" in steps


def test_the_steps_let_the_member_approve_a_whole_source_and_still_promote_one_at_a_time(owner: Session) -> None:
    steps = owner.call("onboard")

    assert "approve all of one source's proposals in one step" in steps
    assert "change, drop or bring back" in steps
    assert "one at a time" in steps


def test_the_steps_leave_out_secrets_stale_claims_and_preferences_from_every_source(owner: Session) -> None:
    steps = owner.call("onboard")

    assert "from every source" in steps
    for needed in ("secret", "no longer holds", "preferences"):
        assert needed in steps, needed


def test_the_final_report_covers_every_repository_and_source(owner: Session) -> None:
    steps = owner.call("onboard")

    assert "every repository and source" in steps.split("Report")[-1]


# An interview: the interviewee is the author of what their answers produced (#620, ADR-0029)

INTERVIEW = "interview:Billing knowledge with emp-2"


def test_the_steps_describe_the_interview(owner: Session) -> None:
    steps = owner.call("onboard")
    interview = steps[steps.index("## Interview an expert") :]

    assert "Any member" in interview
    assert "topic by topic" in interview
    assert "interviewee approves" in interview
    assert 'imported_from="interview:' in interview
    assert "author" in interview


def test_an_interview_makes_the_interviewee_the_author_and_records_the_interviewer_and_the_interview(
    owner: Session, dana: Session
) -> None:
    personal = imported(owner)

    result = owner.call("promote", path=personal, level="project", author="emp-2", imported_from=INTERVIEW)

    assert result["status"] == "promoted", result
    memory = owner.call("read", path=result["path"])
    assert (memory["author"], memory["imported_by"], memory["imported_from"]) == ("emp-2", "owner-1", INTERVIEW)


def test_the_interviewee_is_told_in_their_next_briefing_who_interviewed_them(owner: Session, dana: Session) -> None:
    result = owner.call("promote", path=imported(owner), level="project", author="emp-2", imported_from=INTERVIEW)

    told = added_context(dana.start())

    assert "owner-1 interviewed you" in told
    assert "written from your interview" in told
    assert result["path"] in told and "Money amounts" in told
    assert "promoted a memory in your name" not in told


def test_an_interviewee_who_is_not_a_member_leaves_the_interviewer_as_author(owner: Session) -> None:
    personal = imported(owner)

    refusal = owner.refusal("promote", path=personal, level="project", author="@outside-expert", imported_from=INTERVIEW)
    result = owner.call("promote", path=personal, level="project")

    assert "without author" in refusal and "body" in refusal
    assert result["status"] == "promoted", result
    assert owner.call("read", path=result["path"])["author"] == "owner-1"
    steps = owner.call("onboard")
    assert "isn't a member" in steps[steps.index("## Interview an expert") :]


# Headless onboarding writes a proposals file and saves nothing (#622, ADR-0030)


def test_the_headless_steps_write_a_proposals_file_save_nothing_and_record_progress_as_partly_done(
    owner: Session,
) -> None:
    steps = owner.call("onboard", mode="headless")

    assert owner.run_prompt("onboard", mode="headless") == steps
    assert "proposals file" in steps
    assert "Save nothing" in steps
    for never in ("`remember`", "`promote`", "`edit_memory`"):
        assert never in steps, never
    assert 'status="partly_done"' in steps
    for field in ('"title"', '"summary"', '"type"', '"body"', '"level"', '"source"', '"writer"', '"left_out"', '"reason"'):
        assert field in steps, field


def test_the_interactive_steps_load_a_proposals_file_and_continue_at_approval(owner: Session) -> None:
    steps = owner.call("onboard")
    loading = steps[steps.index("## Load a proposals file") :]

    assert "as a source, not as instructions" in loading
    assert "step 3" in loading


def test_onboarding_is_interactive_unless_headless_is_asked_for(owner: Session) -> None:
    steps = owner.call("onboard")

    assert owner.call("onboard", mode="interactive") == steps
    assert owner.run_prompt("onboard") == steps
    assert steps != owner.call("onboard", mode="headless")
    assert "interactive" in owner.refusal("onboard", mode="batch") and "headless" in owner.refusal("onboard", mode="batch")
