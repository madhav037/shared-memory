---
version: 1
slug: "console-src-app-tsx"
primary_target: "console/src/App.tsx"
related_targets: ["console/src/pages","console/src/theme.ts"]
---

# Console surface brief

## Scope

The whole Shared Memory console: sign-in, the front page, the memory explorer, a memory's page and its history, challenges, project settings, team, audit log and personal token. Visitor mode: **Operate**, with a memory's own page in **Read**.

## Audience and task

Developers first (confirmed 2026-09-19): reading memory like documentation, checking exactly what Claude was told while debugging, following how a memory changed, deciding challenges. The owner, admins and project leads also run members, projects, access and the audit log from the same frame. Visits are short and between Claude sessions, at a desk, sometimes on a phone.

Must stay untouched: every capability and rule in PRODUCT.md, the domain words from CONTEXT.md, the console never writing memory, and a restricted project staying invisible to anyone outside it.

A polished result would feel wrong if it looked like any admin dashboard, if a retired memory could be mistaken for a current one, or if the legal form leaked into the words.

## Direction contract

THESIS: The team's memory is its code of practice, and the console publishes it like a consolidated code: a contents of everything you can reach, each memory set as a citable section whose standing, author and history sit in the margin. It refuses the admin-dashboard arrangement: no sidebar of features, no stat cards, no badge soup.

OWN-WORLD: Public Sans (a government publication grotesk) for every label and control; Source Serif 4 for memory text; the system monospace for paths. Light is the printed page (#f7f8f6 paper, #17211c ink), dark is the bound volume (#101814 cloth, #e4ebe6 ink); one structural accent in buckram green (#1e5b46 light, #7cc4a0 dark) for rules, section marks, the current place and primary actions. Square corners, hairline rules, hanging headings, a ruled right margin. State is a mark and a word, never a hue alone: † superseded, a struck title for retired, ◇ challenged, ⊕ pinned, a dashed rule for personal memory not accepted by the team.

STORY: A member opens the console and sees anything waiting for their decision as a notice, then the contents of every memory they can reach. They open a folder, read a memory exactly as Claude reads it (set as text, or as its source file), check its standing and who changed it when, and move a slider through its history to see what it said on a date. Admins and leads reach Team, project settings and the audit log from the same frame.

FIRST VIEWPORT: A slim masthead: Shared Memory, the team, search, the member. Left, a 300px contents column: Team memory, then each project, each opening to its folders with counts. Right, a reading column capped at 72ch: challenges waiting as a ruled notice when there are any, then the whole contents set as a table of contents, each project and folder with its count and last change on dot leaders. The primary action is opening a memory; search sits in the masthead on every page.

FORM: The Consolidated Code, position 5 of 7 on the grounded list; seed key bb25bb06. Raised by the dealt hand: nothing disappears, it cancels (ticket wallet); weight carried by typographic rank (lineup sheet); every memory and folder addressable and back retracing the trail (HyperCard); state as marks, not hues (cutting bench); a point-in-time slider over a memory's versions (cyclorama); folder labels carrying counts and last change (sneaker wall). Signature interaction: the point-in-time history, where moving through a memory's versions resets the text as it stood, with deletions struck and insertions marked. Motion grammar: 150–200ms state changes only, contents folders expanding in place, no load choreography, reduced motion honoured.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- Build path: code-led (no image generation on this machine), stated rather than asked.
