# The top level is the company

The top-level group of members was the **team**, and team memory held for every project in it. Large customers need levels above a team for rules that many teams share, and a "team" above departments reads backwards. One server still holds one top-level group (ADR-0021 is untouched), so that group is now the **company** and its memory **company memory**; a department sits between it and its projects (ADR-0032). Earlier ADRs say team: read company. Confirmed by the repo's human on 2026-11-21 (#600).

## Considered options

- **Keep team and add a company level above it.** Rejected: one server is one group, so a team and a company on the same server would be the same thing under two names.
- **Organization.** Rejected: it shortens to "org", which collides with GitHub's organizations that members already sign in through.

## Consequences

- The glossary renames first. The code, API fields, routes, console text and README still say team until their own cleanup ticket; `tests/test_glossary.py` allows the old word until then, and that allowance goes with the rename.
- A company of five members is still a company. Plans, hosted servers and license keys name a company, not a team.
