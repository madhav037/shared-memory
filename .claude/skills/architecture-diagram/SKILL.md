---
name: architecture-diagram
description: "Bring the architecture diagram up to date after a feature lands. Run at every spec's retro."
disable-model-invocation: true
---

`docs/architecture.html` is the one-page map of Shared Memory: a standalone HTML document, opened straight from the repository in a browser. Keep its `<!doctype html>`, `<head>` and `<body>` intact. This skill makes the page match `dev` again after work lands. Every spec's retro runs it (#375), so the page is never more than one feature behind.

The page is how the repository's human understands the system without reading diffs. Accuracy is the whole point: read the code for every box, arrow, step and table row you change. Never draw from memory or from the spec. Where you can't confirm something from the code, mark it on the page as unverified.

## Steps

1. **Find the drift.** The page's eyebrow names the commit it was drawn at. List everything since then with `git log --oneline <that commit>..origin/dev`, plus any issue or PR the user named, and `gh issue list --state open` for the status line. Done when every commit since the eyebrow's is on a list you can check off.
2. **Map each change to the page** using the section table below. A change that alters nothing a reader of the page would see (a refactor, a test, a rename inside a module) is skipped, and says why. Done when each listed commit is either assigned to a section or skipped with a reason.
3. **Edit the page.** Follow the drawing rules below. Move the eyebrow to the new `dev` commit and today's date.
4. **Check the script parses:** copy the text between `<script>` and `</script>` to a scratch `.js` file and run `node --check` on it. Done when it exits 0.
5. **Commit** `docs/architecture.html` alone on its own branch and open a PR into `dev`. It is one concern, per `CLAUDE.md`.
6. **Report**: what was drawn, what was skipped and why, anything marked unverified, and the PR link.

## Section table

| Section | Where in the file | Changes when |
| --- | --- | --- |
| How a request travels | `NODES` and `FLOWS` in the script | a new module, entry point, store, or a new path a request takes |
| Containers | the `#containers` `<svg>` and its caption | a container, process, volume, port or outside service changes, or the worker count's default |
| Components | `COMPONENTS`, `DEPS` and `ROWS` in the script | a module is added, removed or renamed, or `build_app()` in `app.py` wires one into another differently |
| Flows, step by step | `SEQ` in the script | a central flow (token check, save, recall, promote, challenge, sign-in, session start, before-edit, collision) gains, loses or reorders a step, or the function doing a step changes |
| Data and storage | the `#data` tree, its "if the server lost a store" list and its table | a table, folder layout, cache, backup content or source-of-truth rule changes |
| Trust boundaries | the `#trust` `<svg>`, the crossings table, the "who may do what" table and the "worth a look" list | an entry point, credential, check, role or permission changes; strike a "worth a look" item once the threat model (#377) decides it |
| Saves take turns per area | `LANES`, the `note` text and the caption | the save path or its concurrency changes |
| What is cached | the `#cache` `<svg>` | a cache, its size or what it holds changes |
| What memory is | the `#memory` `<svg>` and its chips | a new level, type, status, or way memory changes |
| Who can change memory | the `.who` chips and caption | the split between session and console, or roles |
| Tech stack | the `.stack` chips | a dependency or tool is added or removed |
| How it's deployed | the `#deploy` `<svg>` and caption | a container, volume, port, outside service or the deploy path changes |
| Where it stands | the `.status` pills | a spec or ticket opens, merges or closes |
| ADRs | the `<details>` list | an ADR is added, accepted or superseded |

## Drawing rules

- **Glossary words only.** Every label uses `CONTEXT.md`'s term. A member, a repository, a personal token, a level.
- **Name the code.** A component names its file. A flow step names the function that does it, in the step's last field. A trust-boundary row names the check that enforces it.
- **Labels, not prose, in figures.** A node's subtitle is at most four words. A flow step's short label is one phrase. Explanations go in the step's "what happens" field, a table, or the caption.
- **Stay on the grid.** Columns in the system diagram: machines centred at x=90, Caddy at x=300, entry points at x=470, a bus at x=575, modules at x=660, a bus at x=765, state at x=875. Route a flow along these lines. A flow's stop names a node only if the stop's point falls inside that node's box, because that is how the page decides which box lights up.
- **New flow**: in the system diagram, add an entry to `FLOWS` with its `pts`. A point with a third value is a stop and becomes a numbered step. For a step-by-step flow, add an entry to `SEQ` with its actors (at most eight) and steps `[from, to, short, what happens, where in the code]`. `from === to` is a step inside one part. The tabs appear on their own.
- **New component**: add it to `COMPONENTS`, put its id in a `ROWS` layer, and give it a `DEPS` entry listing what it calls, read from `build_app()`.
- **Only what is built.** Planned work belongs on the status line, never in a diagram.
- **Both themes.** New colours come from the `:root` tokens and get a dark value in both dark blocks.
