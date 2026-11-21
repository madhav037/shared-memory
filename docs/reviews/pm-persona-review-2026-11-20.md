# PM persona review — 2026-11-20

Four simulated product managers reviewed the live console (owner's view, demo project Shared Memory). They read a
captured walkthrough of 12 screens plus a Board screenshot; they did not click themselves. Treat this as a list of
objections and confusions, not a prediction of conversion. Method borrowed from `founder-consumer`
(Jakeschincariol/founder-skill): distinct persona cards, told not to be agreeable and not to invent facts.

Not filed as issues yet. Triage from here when the human pulls it in.

## Decisions (2026-11-21)

Filed (needs-triage): 1 → #597 (grill next), 2 → #598, 3+5 → #599, 7 → #600 (grill), 8 → #601, 9 → #602,
10 → #603, 11 → #604 (later), 13 → #605, 15 → #606 (includes the Sessions fragment bug), 16 → #607, 17 → #608.
6 → #609, 12 → #610. Skipped for now: 4, 14, 18–26.

## Ranked list, all rounds (44 personas + a 10-buyer panel)

Ranked by how many raised it, weighted toward the target market (brownfield software teams, product and IT services
companies, failing to become AI-native) and toward what blocks a purchase rather than what annoys.
R1 = first 4 PMs, R2 = 10 PMs, R3 = 30 brownfield, P = buyer panel.

### Blocks adoption
1. **Brownfield bootstrap.** It starts empty; import rules files (and their contradictions), wikis, ADRs, runbooks,
   KT docs, tickets, PR comments, git history into draft memories a human bulk-approves; an expert-interview flow.
   R3 ~26/30, most common "flip to adopt". Must respect ADR-0004/0009 (drafts; an agent judges before promotion).
2. **Enterprise sign-in.** SSO (Entra, Okta, SAML/OIDC), SCIM, and non-GitHub hosts (GitLab, Bitbucket, Azure DevOps).
   R1 1, R2 1, R3 ~22, P 5/10. "Without SSO I pass" 5+ times.
3. **Proof it works.** Recall and briefing hits per memory and per agent, "agent was warned off X", rework or repeated
   review comments down, before/after on one repository; something to put on a slide. R1 1, R2 6/10, R3 ~20, P most flips.
4. **Security and hosting story.** Data residency (India, EU), on-prem and air-gapped with zero outbound calls (CDN
   fonts noticed), where embeddings run, SOC 2 / pen test, vendor-exit guarantee, a named domain instead of sslip.io.
   R1 1, R2 1, R3 ~18, P 5/10.
5. **"What the agents are told."** A briefing preview per project and "what did this session know". R1 4/4, R2 3,
   R3 several. Relates to #282.
6. **Contradictions and duplicates unflagged** (visible in the demo itself), plus memory-vs-code/ADR staleness:
   anchor memory to paths, flag when they change. R1 4/4, R2 ~6, R3 ~15. Relates to #285 and Project health.

### Blocks rollout at scale
7. **Org level and tenancy.** An org above teams, per-client isolation with contractual segregation, per-vendor
   scoping; enterprise per-seat and partner/OEM pricing above 15 members. R1 1, R2 1, R3 all services + platform PMs.
8. **Rollout friction.** Org-level repository setup instead of files committed to 30–120 repositories (services
   teams often can't commit to client repos); central token issue, expiry and revocation. R1 1, R3 ~15, P 2.
9. **Enforcement, not advice.** Protected "do not touch" paths that stop an edit and need a named approver, logged as
   a blocked attempt; rules that can't be superseded from the console. R3 9 (all regulated or ops).
10. **Governance that scales.** Challenges routed by area, squad or keeper; role-based and second approval on critical
    rules; "unverified agent save" and "client-verified" status; evidence link and expiry per memory; age and
    reminders on waiting challenges. R1 1, R2 2, R3 ~12.
11. **Isolation you can prove, and handover.** Make restricted projects (ADR-0006) discoverable and demonstrable; a
    per-project export for client handover; a "who can read this" view incl. personal memory. R1 1, R2 2, R3 3.
12. **Sensitive data.** Secret/PII/PHI scanning on save, quarantine, an owner-only logged purge (GDPR erasure vs
    "never deleted"). R1 1, R2 1, R3 2.

### Shapes whether people understand and trust it
13. **Non-engineers can't add a rule.** A "propose a rule" box queued for the next session to judge and promote,
    and "ask an engineer" with a way to see it was done. R1 1, R2 6/10, R3 3. Needs grilling (ADR-0009).
14. **Brownfield demo project.** Replace the self-referential demo (pytest, pnpm, fonts) and its overdue cards with a
    legacy-looking project. R1 1, R3 ~12.
15. **Plain language.** Gloss or rename supersede, retire, foundation, keeper, gate, briefing, Level, standing,
    Cite as; hide setup behind "for your engineer". R1 4/4, R2 4, P 1 objection.
16. **Focus: memory first.** Board and Sessions read as a second Jira; a memory-only mode with locks optional.
    R1 3/4, R2 1, R3 ~20.
17. **Agent coverage.** State Copilot, JetBrains and Visual Studio support, and show parity across tools. R2 1, R3 ~6.

### Day-to-day usefulness
18. **Cleanup triage.** A queue by stale, last used, doubted, author removed, with bulk retire. R2 2, R3 2.
19. **Why it changed.** A reason on every version, a per-topic decision log, searchable superseded history. R2 1, R3 1.
20. **Audit log for compliance.** Export (CSV, SIEM), reads logged, tamper evidence, filters beyond sign-ins.
    R1 1, R2 1, R3 3.
21. **Async catch-up.** Digest and email/Slack for waiting challenges and changes. R2 2. Relates to #286.
22. **Scope memory by path or language** (a Kotlin agent shouldn't recall Java-only rules). R3 2.

### Polish and copy
23. **Visible bugs.** Sessions-page stray fragment; duplicate "Search" sub-headings; `/search?q=` doesn't search;
    licence banner on every page reads as a warning; font-credit footer. Every round.
24. **Pricing copy and trial.** "No member cap" contradicts the plans; 11–16-person teams fall between tiers; 7-day
    trial too short (30 asked twice). R2 3, R3 4.
25. **Safe clicks.** Confirm "this changes every agent on your team" before Pin, Retire, Accept. R2 1.
26. **Readability.** Low-contrast captions, one green accent for everything, a light-theme option. R1 1, R2 1.

### Positioning (not features)
- Pitch engineers first; the PM approves the spend (P: almost every flip ran through an engineer asking for it).
- For services and outsourcing buyers: "your institutional knowledge stays with you, whichever vendor does the work".
- Price is rarely the objection once proven; the gap is above 15 members.

## The panel

| Persona | Age | Role | Verdict | What would flip it |
| --- | --- | --- | --- | --- |
| Divya | 31 | PM, 10-person fintech team, all on Claude Code | Maybe | Proof a console decision (accept a challenge, pin) changes what agents do next session — a visible "agents followed this" signal |
| Jordan | 26 | Only PM at a 5-person seed startup, uses Notion + CLAUDE.md | Maybe, leaning no; ~$15–25/month for 5 | A 10-minute no-thinking install, and one real contradiction it caught that CLAUDE.md missed |
| Rahul | 45 | Platform PM, 600 engineers, 40 repositories, regulated lines | Maybe — pilot one non-regulated team, self-hosted | SSO + private-by-default projects |
| Margaret | 58 | Non-technical group PM, watches what agents are told | Could not do her job | A plain "what every agent is told at the start" page and a way to ask an engineer for a change |

## Findings, by how many personas raised them

### 1. No way to see what the agents are actually told (4/4)
"What do the agents know about X?" has no answer except Search. All four wanted one page: exactly what a new
session in this project is briefed with, how big it is, and how fresh. Related: #282 (what each session was told).

### 2. Duplicate and contradictory memory sits unflagged (4/4)
In Project memory › Architecture: "A save embeds its memory before taking its turn" beside "…inside its turn";
"Saves serialize behind one lock" beside "Saves take turns per area". To a PM this is the exact drift the product
promises to stop. Want "possible duplicates" and "unused for 90 days" on Contents, not buried in
Settings › Project health. Related: #285 (similar memories on save), Project health.

### 3. Vocabulary shuts PMs out (4/4)
Terms nobody could parse without help: supersede, retire, foundation, keeper, gate, briefing, Level (search filter),
Standing, "Cite as" path, "As your agent reads it" vs "Text", "Promoted … in Claude Code", "Memory pinned — A whole
topic". ("seam" came from memory content, not the console.) Ask: a one-line gloss beside each term, or plainer
labels; hide setup material behind a "for your engineer" link.

### 4. Visible rough edges (4/4) — likely bugs
- Sessions page shows a stray fragment: "when a message or a gate for you arrives while the page is open." —
  probably a notification toggle whose label doesn't render.
- Folder view shows "Search" twice as a sub-heading (a sub-topic under Architecture and under Conventions) with no
  parent shown.
- Footer "Set in Cooper Hewitt, Charis SIL and Source Code Pro." read as noise.
- The licence banner on every page read as a warning or billing problem (3/4).
- `/search?q=…` in the URL doesn't run a search.

### 5. The Board reads as scope creep (3/4)
"Why is a Jira clone in a memory tool?" Overdue demo cards (31 Oct, 24 Oct) and Done 0 made it look abandoned.
Partly a demo-data problem: refresh the seed's due dates.

### 6. No path from "this is wrong" to "it's fixed" for a non-engineer (2/4)
The console can't edit memory (ADR-0009, by design). PMs didn't know that Retire ≠ correct, couldn't write the
right version, and couldn't later check an engineer had done it. Ask: on a memory page, "To change this, ask an
engineer to do it from their coding agent" with a one-click request, and a way to see it was done.

### 7. Decisions without visible effect (2/4)
After Accept on a challenge: does every agent act on it immediately? Who can push back? Who decides when the author
has left?

### 8. Enterprise rollout blockers (Rahul)
- GitHub-only sign-in; needs SAML/OIDC with group→role mapping and SCIM deprovisioning.
- Members added one at a time; most show GitHub "not linked".
- Default "Open to the whole team"; regulated lines need private by default. (Restricted projects exist — ADR-0006 —
  the demo project just isn't one; the console didn't make that option discoverable.)
- No pre-save secret/PII scanning, no quarantine, no auditable admin purge. "Memory the team has accepted is never
  deleted" conflicts with GDPR erasure.
- Onboarding 40 repositories by hand-merging JSON + a ~40-line AGENTS.md block each.
- Any member can start a project; no admin gate.
- Audit log: no export/SIEM feed, reads not logged, tamper-evidence and retention unstated.
- Compliance questions the console doesn't answer: data region and tenancy, encryption at rest, embedding provider
  (does text leave the boundary?), token rotation/expiry, SOC 2 / pen test, prompt injection via briefings.

### 9. Value versus Notion + CLAUDE.md (Jordan)
Wins: resolving two agents' disagreement in one diff screen; agents write memory themselves. Loses: CLAUDE.md is
free, in the repository, zero setup, edited in PRs. No visible case of it catching something that mattered. Ask: a
one-sentence promise on the home screen and a before/after.

## What landed well
- **Challenges** side-by-side diff — every persona's favourite screen; Accept/Reject labels clear.
- **Pin into every briefing** — the lever PMs want.
- "Challenged … Until you decide, it stands as it is." — reassuring.
- Provenance (Cite as, versions), audit log presence, data export, rate limits — reassured the platform PM.
- Calm dark theme and large serif body text; weaker: low-contrast grey captions, tiny monospace paths, one green
  accent for everything so the primary action doesn't stand out.

## Round 2: ten more PMs, one per project situation

Same method as the first four (walkthrough + screenshot, Sonnet, in character, not agreeable), each judging it for
a concrete job in their own project.

| Persona | Age | Situation | Verdict | Flips it |
| --- | --- | --- | --- | --- |
| Aisha | 24 | First PM job, 9 engineers, afraid to change things for everyone | Pilot | A read-only "what did this session's agent know" view |
| Ken | 38 | Agency, 4 clients, contractors churn monthly | Pilot | Tested guarantee outsiders can't read/search/export a project; a per-project handover zip |
| Elena | 52 | Head of Product, budget owner, 14 engineers | Pass for now | Write and pin a decision herself, with "reached 14 of 14 engineers" |
| Tunde | 29 | Ex-engineer, will install it tonight | Pilot ($49) | Edit hooks/locks optional (memory-only mode) and recall hits shown on rejected decisions |
| Priscilla | 61 | Healthcare, HIPAA, auditors | Pass; pilot on a non-clinical repo | Enforced no-PHI control on save and a logged hard delete |
| Marco | 35 | Remote, 3 time zones, a new hire a month | Pilot ($89) | A "since you were last here" digest; preview of a new hire's briefing |
| Hannah | 44 | Mobile team on Cursor + Codex + Claude Code | Pilot ($89) | Per-agent report: the same rule recalled/applied in each tool |
| Dev | 33 | Inherited 6 months of stale memory; authors left | Pilot ($49) | Stale/conflicting queue with bulk retire and an "author left" filter |
| Grace | 27 | Non-technical solo founder, 2 contractors | Pilot ($49 only) | Write a rule herself without a coding agent; setup without a developer |
| Victor | 49 | Monolith migration, decisions change weekly | Pilot (wants 30-day trial) | Sessions visibly warning when two teams' agents work against each other |

**8 pilot, 2 pass, 0 adopt.**

### New themes (beyond round 1)

1. **PMs can't write a rule (6/10: Elena, Grace, Marco, Hannah, Victor, Tunde).** The biggest finding, and it collides
   with ADR-0009 (the console never writes memory, because promotion needs an agent to judge contradictions). Hannah
   proposed the shape that respects it: a "propose a rule" box that queues the text for the next coding agent session
   to judge and promote, like a challenge in reverse. Needs grilling, not a quick fix.
2. **No evidence agents follow memory (6/10: Hannah, Tunde, Elena, Dev, Victor, Aisha).** Want recall/briefing counts
   per memory, per agent tool, and "recalled and the agent changed course". Project health shows usage, not
   compliance.
3. **Cleanup triage (Dev, Victor).** A queue sorted by stale / last used / doubted / author removed, with bulk retire.
   Challenges only exist when someone raises one, and a waiting challenge has no age or reminder while the old rule
   keeps being served.
4. **"Why it changed" (Victor).** Versions say "Promoted by <member>", not the reason; want a per-topic decision log.
   Search excludes superseded memory, so history isn't searchable.
5. **Client isolation and handover (Ken).** Restricted projects exist (ADR-0006) but the console didn't make that
   discoverable or provable; there's no per-project export, only the whole-team zip.
6. **Async catch-up (Marco).** A digest of what changed while you slept; relates to #286.
7. **Memory-only mode (Tunde).** The before-edit lock hook is a deal-breaker for some; want briefing + recall without
   locks, sessions, board.
8. **Safe clicks (Aisha).** A confirm step saying "this changes every agent on your team" before Pin, Retire, Accept;
   or a read-only role.
9. **Sensitive data (Priscilla, echoing Rahul).** PHI/PII guard on save, owner-only logged purge, a "who can read
   this" matrix including personal memory, exportable audit log with reads, a named domain (sslip.io looked
   unprofessional), BAA.
10. **Pricing confusion (Elena, Victor, Grace).** The Team page's "this server has no member cap" contradicts the
    5/10/15 plans; a 14-person team lands on $129 for a tool its PM can't type into; 7 days is too short to see a
    rule change land (Victor wants 30).

## Round 3: 30 personas on the target market (brownfield teams failing to become AI-native)

Same method, sharper brief: each persona judged it from inside a brownfield software organisation whose AI-native
push is failing. 20 brownfield PMs at product companies (banking, insurance, Magento, Rails SaaS, telecom, SAP,
logistics, edtech, HL7, ad-tech, public sector, merger, HR/payroll, games, retail POS, 300-engineer SaaS, travel,
young startup, utility) and 10 others: 6 from the IT services side (TCS/Infosys/Wipro-scale delivery head, GenAI CoE
lead, fixed-price engagement manager, presales architect, rotated offshore developer, client-side vendor manager) and
4 product-company roles (sceptical senior developer, tech lead, CTO, staff architect).

**24 pilot · 6 pass · 0 adopt.** Passes: public-sector air-gap (Fiona), HR/payroll director with hostile seniors
(Brian), and four from the services side (delivery head, CoE lead as a partner, presales, offshore developer). Many
"pilots" are conditional: "without SSO I pass" came up 5+ times. Price was almost never the objection.

### What the target market says, ranked by how many raised it

1. **Cold start: it starts empty, and brownfield knowledge isn't in anyone's agent sessions (~26/30).** The single
   loudest finding and the most common "flip to adopt". Asks: import CLAUDE.md / AGENTS.md / rules files (and find
   contradictions across 45 of them), Confluence and wikis, ADRs, runbooks, KT documents, old tickets, PR review
   comments, git history; "scan the repo, propose draft memories, I bulk-approve"; a guided interview that drafts a
   departing expert's knowledge for them to approve.
2. **Proof it works (~20/30).** Every buyer needs a number for someone: the "30% productivity" slide, the CTO's
   ROI question, defects on agent-written code, a client renewal deck, a change board. Asks: recall hits per memory
   and per agent, "agent was warned off X", rework or repeated review comments reduced, before/after on one repo.
3. **GitHub-only sign-in is a hard stop (~22/30).** Entra ID, Okta, SAML/OIDC, SCIM; and many teams aren't on
   GitHub at all (GitLab, Bitbucket, Azure DevOps, internal Git).
4. **Security and hosting story missing (~18/30).** The sslip.io address read as hobbyware; asks for data residency
   (India and EU named), on-prem and air-gapped install with zero outbound calls (the CDN fonts card was noticed),
   where embeddings run, SOC 2 / pen test, what happens if the vendor dies (the "plain files in git" design and export
   reassured, if contracted).
5. **The demo shows a greenfield team, not them (~12/30).** Demo memory is the tool's own repo (pytest, pnpm, fonts);
   nobody could picture their settlement rules or COBOL boundary. A brownfield demo project would sell better.
6. **Advisory, not a control (~9/30, all regulated or ops).** Want protected "do not touch" paths that stop an edit
   and need a named approver, logged as a blocked attempt; a "board-ratified, can't be superseded in the console"
   rule. Locks were understood as collision control, not protection.
7. **Governance doesn't scale (~12/30).** The owner/author decides every challenge; at 40+ engineers that's a
   bottleneck or politics. Want routing by area/squad/keeper, role-based approval, a second approver on critical rules,
   a "client-verified" or "unverified agent save" status, evidence links and expiry on memories.
8. **Rollout friction (~15/30).** Committing settings + a 40-line AGENTS.md to 14/30/80/120 repositories (and
   services teams often can't commit to client repos); hand-issued personal tokens for 45–600 people. Want org-level
   setup and centrally managed tokens.
9. **Contradictions visible in the demo (~15/30)**, and for the architect, memory vs code vs ADR reconciliation:
   anchor memory to paths, flag it stale when they change, treat imported ADRs as authoritative.
10. **Scale and tenancy (all services personas, plus the 300-engineer platform PM).** An org level above teams,
    per-client isolation with contractual segregation, per-vendor access scoping, the 15-member cap and "talk to
    us" (want per-seat enterprise and OEM/partner pricing).
11. **Board and Sessions read as scope creep (~20/30)**: "I already have Jira".
12. **Agent coverage unclear (~6/30)**: Copilot (named by most services personas), JetBrains, Visual Studio.
13. **Scoping by codebase or language (Tomoko)**: a Kotlin agent must not recall Java-only rules.

### Services-side angle worth keeping
The client-side vendor manager (Karen) framed the strongest positioning in the round: *the client's institutional
knowledge stays with the client, in the client's environment, whichever vendor's engineers and agents do the work*.
She wants a per-application "knowledge coverage" view before letting a vendor go. The services delivery side wants the
opposite boundary: per-client tenants, a client-facing productivity report, and a white-label/OEM licence. The CoE
lead's honest note: "the core, yes" they could build in a quarter; the governance UI and cross-agent hooks are the moat.

### Pricing signals
$49 is an approve-without-a-meeting line item; $89–129 is "trivial" against contractor or vendor cost once proven.
The real pricing gap is above 15 members and for services firms. Two asked for a 30-day trial (7 days is too short
for memory to accumulate).

## Buyer panel (founder-consumer, 10 Sonnet buyers, seed 20261120)

Pitch: the product in five lines with the draft team prices ($49/$89/$129 a month cloud, yearly and self-hosted
options, 7-day trial, no free plan). Cards covered all four segments (seed, scale-up, enterprise, agency) and all
eight behaviours, ages 26–59.

**0 buy · 10 pass.** Simulated buyers lean agreeable, so even 0% is an upper bound on a cold pitch.

| Why they pass | Buyers | Gist |
| --- | ---: | --- |
| trust | 5 | No SSO, no security page, no word on where code knowledge lives; security would block the trial |
| need | 3 | CLAUDE.md + a decisions file does most of it free; setup is engineers' time they'd have to sell |
| habit | 2 | Notion + Linear + CLAUDE.md, nobody's complaining; can't measure a $49–129 bill |

What flips a no (repeated across buyers): a security page (data location, retention, SSO, SOC 2 or self-host inside
the network); an engineer asking for it and doing the setup; a measured before/after on one real repository
("agents stopped contradicting pinned decisions"); setup that doesn't touch every repository.

Price sensitivity (Van Westendorp): acceptable range **$21–$110 a month**, least-resistance ~$21, indifference ~$59;
medians — too cheap $15, bargain $39, getting expensive $90, too expensive $160. The 5-member $49 plan sits inside
the range; $129 for 15 sits above the point where too many call it too expensive.

The PM is not the buyer to pitch first: almost every flip runs through an engineer asking for it.

## Candidate issues as gathered per round (superseded by the ranked list above)
1. Bug: Sessions page notification-toggle label renders as a stray sentence fragment.
2. Bug: duplicate "Search" sub-headings in the folder view.
3. Plain-language glosses for console terms.
4. Duplicates and staleness surfaced on Contents (fold into #285 / Project health).
5. "What agents are told" page (comment on #282).
6. Ask-an-engineer request path from a memory page.
7. SSO/SCIM.
8. Secret/PII scanning before save, plus an auditable purge.
9. Demo seed: refresh card due dates.
10. Grill: a PM proposes a rule from the console, queued for a session to judge (must respect ADR-0009).
11. Evidence of use: recall/briefing counts per memory and per agent tool.
12. Cleanup triage queue with bulk retire and an "author removed" filter; age and reminders on waiting challenges.
13. A reason on every version; searchable superseded history.
14. Per-project export for handover; make restricted projects discoverable from Settings.
15. Memory-only mode: locks and sessions optional.
16. Confirm step on team-wide actions (Pin, Retire, Accept).
17. Pricing copy: "no member cap" vs plans; trial length.
18. Grill: brownfield bootstrap: import rules files / docs / ADRs / tickets into draft memories a human bulk-approves
    (and an expert-interview flow). Must respect ADR-0004/0009 (an agent judges contradictions before promotion).
19. SSO (Entra/Okta, SAML/OIDC, SCIM) and non-GitHub hosts (GitLab, Bitbucket, Azure DevOps).
20. A security and hosting page: residency, on-prem/air-gap, embeddings location, zero outbound calls, vendor exit.
21. Protected paths: an enforced "do not touch" with a named approver and a logged blocked attempt.
22. A brownfield demo project to replace the self-referential demo data.
23. Org level above teams: per-client tenancy, enterprise and partner pricing.
24. Org-level repository setup and central token management.
