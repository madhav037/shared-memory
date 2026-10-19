# Shared Memory

A memory server every member's coding agent reads and writes, plus a console for governing it.
`PRODUCT.md` says what it is for. `CONTEXT.md` says what everything is called.

## Naming and decisions bind

**`CONTEXT.md`'s glossary is authoritative for naming.** Identifiers, routes, columns, API
fields, test names and UI strings use the glossary's term. Each entry also lists the synonyms
to keep out: a *member*, never a user; a *repository*, never a repo; a *personal token*, never
an API key; a *level*, never a tier or scope. A concept the glossary lacks means you are either
inventing language this project doesn't use or you've found a real gap — settle it through
`.claude/skills/domain-modeling` before it reaches code.

**The ADRs in `docs/adr/` bind.** Code contradicting one is wrong until that ADR is superseded.
Load-bearing above the rest: **ADR-0009 — the console governs memory but never writes it.** From
the console a member pins, unpins, decides challenges and retires; writing, editing and promoting
belong to a session, because promotion needs a coding agent to judge contradictions (ADR-0004)
and a web page has no model to do it. A console route that saves, edits or promotes a memory is
a bug.

## The feature path

Every feature walks this spine, in order, through the skills vendored in `.claude/skills/`:

```
grill-me → domain-modeling → to-spec → to-tickets → implement-spec → code-review → retro
```

- **grill-me** — interrogate the idea until the shape holds.
- **domain-modeling** — only when the vocabulary is unsettled: new terms, or terms the glossary
  and the code disagree about. Settled vocabulary skips straight to `to-spec`.
- **to-spec** — publish the spec as a GitHub issue.
- **to-tickets** — split the spec into tracer-bullet tickets with their blocking edges.
- **implement-spec** — one PR per ticket, test-first.
- **code-review** — review the branch against the repo's standards and the originating issue.
- **retro** — what the session learned, written down.

`triage` keeps the issue list healthy between features.

**A feature request arriving mid-session is filed, not built.** Run
`gh issue create --label needs-triage`, then carry on with the work in hand. It enters the spine
when the repo's human asks for it.

## Checks

Run the seam you're touching while iterating, and the whole table once before each commit.

| Seam | Command |
| --- | --- |
| Python lint | `uv run ruff check` |
| Python tests | `uv run pytest` |
| Python types | `uv run mypy` |
| Console build and types | `cd console && npm run build` |
| Console units | `cd console && npm run test` |
| Console JSON API contract | `cd console && npm run api:check` |
| Console journeys | `cd console && npx playwright test` |

The two seams that carry the product are tested through their real surface: the **Session driver
over HTTP** (drive it with a test client, not by calling handlers directly), and the **console's
JSON API plus its Playwright journeys**. A new endpoint or screen lands with coverage at its
seam.

## Pull requests

- One PR per ticket: one concern, a small diff. Cleanup travels in its own PR.
- Merge when CI is green: queue it with `gh pr merge --auto --squash` as soon as the PR is open, and
  GitHub merges it once the `checks` job passes. CI runs only the side a PR can affect (server,
  console, or both), so don't wait on it.
- **Stacked PRs:** merge the base with `gh pr merge --squash` and leave its branch in place.
  Deleting the base branch makes GitHub close the stacked PR instead of retargeting it, so
  `--delete-branch` waits until every PR stacked on it has merged. Then move the stacked branch
  onto the squashed base with `git rebase --onto origin/main <old base>`.
- **Several agents at once:** each works in its own worktree. See `docs/agents/worktrees.md`.
- **Review** reads `CODING_STANDARDS.md`.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues for madhav037/shared-memory, managed with the `gh` CLI.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels: needs-triage, needs-info, ready-for-agent, ready-for-human,
wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
