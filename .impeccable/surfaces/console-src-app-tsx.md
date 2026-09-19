---
version: 2
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

OWN-WORLD (revised 2026-09-19: the user asked for it to look modern, not old-style, and not like generic AI output): a modern public register rather than an antique book. Crisp white paper (#ffffff, panels #f6f7f7) and near-black ink (#111415); dark is #0f1112 with #eef1f1 ink. Cooper Hewitt, a museum collection's own open grotesk, carries titles and every label and control, set large and tight for titles, never uppercase-tracked. Charis SIL (Charter's lineage) is kept for memory text only, the one thing read at length. Source Code Pro for paths, sources and citation stamps. One signal green (#00703c light, #4cc38a dark, GOV.UK's button green) for in force, the current place and primary actions, with GOV.UK's solid button and darker bottom edge. Functional inks only where they carry state: red (#d4351c) for challenges and taking away, amber for reading a memory as it stood at an earlier point in time, and GOV.UK focus yellow (#ffdd00) for keyboard focus and search matches. Square corners, hairline rules, a heavier bottom edge on the one status box, hanging heads, a ruled right margin. State is a mark and a word: † superseded, a struck title for retired, bracketed insertions with numbered notes and rows of dots where words were removed.

STORY: A member opens the console and sees anything waiting for their decision as a notice, then the contents of every memory they can reach. They open a folder, read a memory exactly as Claude reads it (set as text, or as its source file), check its standing and who changed it when, and move a slider through its history to see what it said on a date. Admins and leads reach Team, project settings and the audit log from the same frame.

FIRST VIEWPORT: A slim masthead: Shared Memory, the team, search, the member. Left, a 304px contents column: Team memory, then each project, each opening to its folders with counts. Right, a reading column capped at 74ch: challenges waiting as a ruled notice when there are any, then the whole contents set as a table of contents, each project and folder with its count and last change on dot leaders. The primary action is opening a memory; search sits in the masthead on every page.

FORM: The Consolidated Code, position 5 of 7 on the grounded list; seed key bb25bb06. Raised by the dealt hand: nothing disappears, it cancels (ticket wallet); weight carried by typographic rank (lineup sheet); every memory and folder addressable and back retracing the trail (HyperCard); state as marks, not hues (cutting bench); a point-in-time slider over a memory's versions (cyclorama); folder labels carrying counts and last change (sneaker wall). Signature interaction: the point-in-time history, where moving through a memory's versions resets the text as it stood, with deletions struck and insertions marked. Motion grammar: 150–200ms state changes only, contents folders expanding in place, no load choreography, reduced motion honoured.

DEVICES (each carries information; none is costume):
- Currency line under every title: first written, last amended, by whom, and how many versions (Justice Laws Canada "current to … and last amended on …"; GOV.UK "Last updated … see all updates"; SEP "First published …; substantive revision …").
- One status box per memory, the only tinted element in its head, in one of four states: in force (signal green), challenged (red), superseded or retired (paper), read as it stood (amber) (legislation.gov.uk "Changes to legislation" box and its point-in-time variant).
- Amendment markup: an earlier version's changes as bold bracketed insertions with numbered markers and dots for removed words, keyed to an Amendments list under the text (legislation.gov.uk F-notes and repeal dots).
- History as plain sentences with closed date ranges, newest first (Justice Laws point-in-time index; Cooper Hewitt's object timeline).
- A copyable citation stamp, path at a version (EUR-Lex document stamp).
- Italic labels in place of uppercase tracking, and italic for the current place (Tufte CSS; Hyphen Press).
- Cross-references with a dotted underline that turns solid (Cornell LII); keyboard focus as a highlighter fill with an ink bar (GOV.UK).
- A colophon at the foot of the contents saying how the record is kept.

REFERENCES (pre-2022, read from their CSS by two research passes on 2026-09-19): legislation.gov.uk (2019), Justice Laws Website Canada (2019), Cornell LII (2019), eCFR (2021), EUR-Lex (2020), GPO Style Manual (2016), Practical Typography (2019), Tufte CSS (2018), GOV.UK Design System (2020), iA (2019), Craig Mod (2018), Stripe API reference (2017), Stanford Encyclopedia of Philosophy (2019), Hyphen Press (2014), Public Books (2015), Harvard Law Review (2015), Cooper Hewitt collection (2016).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- Build path: code-led (no image generation on this machine), stated rather than asked.
