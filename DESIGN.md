---
name: Shared Memory
description: The team's memory published as a modern public register, in white paper, near-black ink and one signal green.
colors:
  paper: "#ffffff"
  paper-2: "#f6f7f7"
  paper-3: "#eceeef"
  ink: "#111415"
  ink-2: "#3c4346"
  ink-3: "#5e676b"
  rule: "#d8dcde"
  rule-soft: "#e8ebec"
  accent: "#00703c"
  accent-hover: "#005a30"
  accent-edge: "#002d18"
  accent-ink: "#ffffff"
  accent-wash: "#e8f4ed"
  danger: "#d4351c"
  danger-hover: "#aa2a16"
  danger-edge: "#55150b"
  danger-wash: "#fbeae7"
  past: "#7a4f00"
  past-rule: "#e09a1b"
  past-wash: "#fff5e1"
  highlight: "#ffdd00"
  highlight-ink: "#0b0c0c"
  highlight-soft: "#fff1a8"
  field-edge: "#6f787c"
  band: "#111415"
  band-2: "#2a2f31"
  band-ink: "#ffffff"
  band-ink-2: "#c9cfd1"
  band-accent: "#4cc38a"
  paper-dark: "#0f1112"
  paper-2-dark: "#151819"
  paper-3-dark: "#1f2325"
  ink-dark: "#eef1f2"
  ink-2-dark: "#c3c9cc"
  ink-3-dark: "#98a1a5"
  rule-dark: "#2e3336"
  rule-soft-dark: "#222628"
  accent-dark: "#4cc38a"
  accent-hover-dark: "#6fd3a3"
  accent-edge-dark: "#1d6b45"
  accent-ink-dark: "#0b0d0e"
  accent-wash-dark: "#122a1e"
  danger-dark: "#ff7a66"
  danger-hover-dark: "#ff9989"
  danger-edge-dark: "#7a2417"
  danger-wash-dark: "#2e1612"
  past-dark: "#f2b544"
  past-wash-dark: "#291f0c"
  highlight-soft-dark: "#574a00"
  field-dark: "#0b0d0e"
  field-edge-dark: "#7c868a"
  band-dark: "#050606"
  band-field-dark: "#1b1f21"
typography:
  display:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "clamp(3rem, 8vw, 6rem)"
    fontWeight: 700
    lineHeight: 0.95
    letterSpacing: "-0.04em"
  headline:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "2.75rem"
    fontWeight: 700
    lineHeight: 1.06
    letterSpacing: "-0.028em"
  title:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.018em"
  standfirst:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "1.1875rem"
    fontWeight: 400
    lineHeight: 1.5
  summary:
    fontFamily: '"Charis SIL", Charter, "Bitstream Charter", Cambria, Georgia, serif'
    fontSize: "1.25rem"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: '"Charis SIL", Charter, "Bitstream Charter", Cambria, Georgia, serif'
    fontSize: "1.1875rem"
    fontWeight: 400
    lineHeight: 1.68
  memory-name:
    fontFamily: '"Charis SIL", Charter, "Bitstream Charter", Cambria, Georgia, serif'
    fontSize: "1.1875rem"
    fontWeight: 700
    lineHeight: 1.3
  ui:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  control:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "0.9375rem"
    fontWeight: 600
    letterSpacing: "0.005em"
  meta:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 400
    fontFeature: '"tnum"'
  label:
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 400
    letterSpacing: "normal"
  mono:
    fontFamily: '"Source Code Pro Variable", "Source Code Pro", ui-monospace, Menlo, Consolas, monospace'
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  none: "0px"
spacing:
  masthead: "60px"
  contents: "304px"
  margin-column: "256px"
  measure: "68ch"
  page-measure: "760px"
  register-measure: "1000px"
  page-top: "44px"
  page-side: "56px"
  page-foot: "104px"
  gutter: "56px"
  section: "52px"
  page-side-small: "16px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
  button-danger-hover:
    backgroundColor: "{colors.danger-hover}"
  button-default:
    backgroundColor: "{colors.paper-3}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
  button-default-hover:
    backgroundColor: "{colors.rule-soft}"
  quiet-link:
    textColor: "{colors.accent}"
    typography: "{typography.meta}"
  quiet-link-danger:
    textColor: "{colors.danger}"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
  masthead:
    backgroundColor: "{colors.band}"
    textColor: "{colors.band-ink}"
    height: "{spacing.masthead}"
  nav-link:
    textColor: "{colors.band-ink-2}"
    typography: "{typography.ui}"
    padding: "0 12px"
  nav-link-current:
    textColor: "{colors.band-ink}"
  count:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.band-ink}"
    height: "20px"
  tree-row:
    textColor: "{colors.ink-2}"
    typography: "{typography.ui}"
    height: "32px"
  tree-row-current:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
  status-in-force:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "13px 16px 12px"
  status-challenged:
    backgroundColor: "{colors.danger-wash}"
    textColor: "{colors.ink}"
  status-past:
    backgroundColor: "{colors.past-wash}"
    textColor: "{colors.ink}"
  status-cancelled:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
---

# Design System: Shared Memory

## Overview

**Creative North Star: "The Consolidated Code, as a Modern Public Register"**

The console publishes the team's memory the way a government publishes its consolidated law online: a contents of everything a member can reach, each memory set as a citable section, and its standing, author and history in a ruled right margin. It is a modern public register rather than an antique book. Crisp white paper and near-black ink carry nearly everything; one signal green marks what is in force, the current place and the action to take. Red, amber and highlighter yellow appear only where they carry state. Dark is the same register at night, with no tint of its own.

The density is that of a reference site, not a dashboard. A dark masthead band with the signal green along its foot, a contents column on a barely grey panel, and a reading column held to a book measure with the margin beside it. Weight is carried by typographic rank (bold against regular, upright against italic, whole against struck through) and by rules, never by colour fields, cards or badges. Hairline rules, heavier ink rules at the head of a list, dot leaders and version numbers hanging in the gutter do the structural work that boxes and shadows do elsewhere.

Every device carries information and comes from a named public source (see References below). The system refuses the admin-dashboard arrangement (no sidebar of features, no stat cards, no badge soup) and the antique look it replaced: no tinted paper, no book greens, no uppercase-tracked labels. Nothing disappears; superseded and retired memory keeps its place, visibly cancelled. Motion is limited to state changes on one ease-out, and reduced motion is honoured.

**References (all read from their live CSS; each device's source is named where the device is described):**

- **GOV.UK Design System (2020):** the dark masthead band with a coloured foot, the signal green (#00703c) and red, the solid square button standing on a darker 2px edge, the yellow focus highlighter with an ink bar, the "Last updated" currency line.
- **legislation.gov.uk (2019):** the one status box with a heavier foot and its point-in-time variant; amendment markup (bold square brackets, numbered F-style markers, rows of dots for removed words) keyed to an Amendments list.
- **Justice Laws Website Canada (2019):** "current to … and last amended on …" and the point-in-time index behind the history's closed date ranges.
- **Stanford Encyclopedia of Philosophy (2019):** "First published …; substantive revision …" in the currency line.
- **Cooper Hewitt collection site (2016):** its own open grotesk, Cooper Hewitt, for every title, label and control; an object's history told in sentences.
- **EUR-Lex (2020):** the copyable citation stamp, a path at a version.
- **Cornell LII (2019):** cross-references with a dotted underline that turns solid.
- **Tufte CSS (2018), Hyphen Press (2014):** italic labels in place of uppercase tracking; italic for the current place.
- Also consulted for measure, rules and restraint: Justice Laws, eCFR (2021), GPO Style Manual (2016), Practical Typography (2019), iA (2019), Craig Mod (2018), Stripe API reference (2017), Public Books (2015), Harvard Law Review (2015).

**Key Characteristics:**
- White paper and near-black ink; light and dark are the same neutral register, not tinted.
- One signal green for in force, the current place, links and primary actions; red, amber and yellow only where they carry state.
- Cooper Hewitt for everything operated and every title; Charis SIL for a memory's own words; Source Code Pro for paths, sources and citations.
- Square corners, hairline rules, heavier ink rules heading lists, dot leaders, a ruled right margin.
- State is a mark and a word; a memory's weight is type rank.
- Flat: depth is a step of paper or a rule. The only raised things are buttons on their edge and menus that float.

## Colors

A neutral register: white, three near-greys and near-black ink, with one green and three functional inks that each mean exactly one thing. Every colour is a custom property on `:root`, redefined under `[data-mantine-color-scheme="dark"]`; the framework's own palette is pointed at them.

### Primary
- **Signal Green** (`accent`; `accent-dark` at night): what is in force, the current place, links, primary buttons, a checked control, the pinned mark, the version part of a citation stamp. GOV.UK's button green; 6.2:1 on paper.
- **Deep Signal** (`accent-hover`): hover on green buttons and links.
- **Signal Edge** (`accent-edge`): the 2px edge a green button stands on.
- **Signal Wash** (`accent-wash`): the in-force status box, the current row in the contents tree, a just-issued token slip. The only green surfaces.
- **Band Green** (`band-accent`): the 4px foot of the masthead, the current nav item's underline and the wordmark's square. The same green in both schemes, because the band is dark in both.

### Secondary
- **Challenge Red** (`danger`): a challenge, a refusal, an action that takes something away (retire, remove), the waiting count. With its own `danger-hover`, `danger-edge` and `danger-wash`.

### Tertiary
- **Point-in-Time Amber** (`past` for text, `past-rule` for the box's rule, `past-wash` for its fill): reading a memory as it stood at an earlier version, and nothing else. `past-rule` is a rule colour, not an ink: never set text in it.
- **Highlighter Yellow** (`highlight`, with `highlight-ink`): keyboard focus and the skip link. `highlight-soft` marks search matches, a targeted amendment note and, in light, text selection.

### Neutral
- **Paper** (`paper`): the page, fields, menus.
- **Panel** (`paper-2`): the contents column, the current version's row, source and settings blocks, a cancelled status box.
- **Hover Paper** (`paper-3`): row hover, inline code, default buttons, loading bars.
- **Ink** (`ink`), **Second Ink** (`ink-2`), **Third Ink** (`ink-3`): text in three ranks.
- **Rule** (`rule`) and **Soft Rule** (`rule-soft`): hairlines between parts and between entries.
- **Field Edge** (`field-edge`): the edge of a text field and a default button's edge, at 4.5:1 on paper.
- **Band** (`band`, `band-2`, `band-ink`, `band-ink-2`): the masthead: near-black, its divider and hover underline, white and second ink on it.

### Named Rules
**The One Meaning Rule.** Each hue means one thing. Green is in force, here, and go; red is challenged or taken away; amber is an earlier point in time; yellow is focus or a match. Nothing else on the page is coloured.

**The Mark-and-Word Rule.** State is a mark and a word, never a hue alone. Every coloured status box leads with an icon or the dagger and a bold word ("In force.", "Challenged.", "Superseded.", "Retired.", "As it stood: version 2 of 3.").

**The Third-Ink Rule.** Third ink is the lowest text rank and stays on paper, panel, hover paper and the washes (4.97:1 at worst). Nothing lighter carries text.

## Typography

**Display Font:** Cooper Hewitt (with Helvetica Neue, Arial)
**Body Font:** Charis SIL (with Charter, Bitstream Charter, Cambria, Georgia) for a memory's own words
**Label/Mono Font:** Cooper Hewitt for labels; Source Code Pro for paths, the source view and citation stamps

**Character:** A museum's open grotesk set large, bold and tight for titles and plainly for everything operated, against a sturdy Charter-lineage serif for the text people actually read. Loaded weights: Cooper Hewitt 400, 500, 600, 700 (italics at 400, 500, 700); Charis SIL 400 and 700 with italics.

### Hierarchy
- **Display** (700, clamp(3rem, 8vw, 6rem), 0.95, -0.04em): the title page only, before sign-in and when the server can't be reached.
- **Headline** (700, 2.75rem, 1.06, -0.028em; 2rem at 900px and below): one page title per page, balanced, capped at 24ch.
- **Title** (700, 1.5rem, -0.018em): section headings and table-of-contents part names; 1.375rem for a disputed memory's head, 1.25rem for a part head in a folder, 1.0625rem for sub-headings.
- **Standfirst** (400, 1.1875rem, 1.5, second ink, 60ch): the paragraph under a page title.
- **Summary** (Charis SIL 400, 1.25rem, 58ch): a memory's summary under its title, set as its text is.
- **Body** (Charis SIL 400, 1.1875rem, 1.68, 68ch, hanging punctuation): a memory's text, the text as it stood, and headings inside it in Cooper Hewitt 700.
- **Memory name** (Charis SIL 700, 1.0625 to 1.1875rem): a memory's name in lists, results, notices, facing texts and as a contents leaf (0.9375rem, regular; bold italic when current).
- **UI** (400 to 500, 0.9375rem): nav, tree rows, status boxes, registers, margin values.
- **Control** (600, 0.005em): button text.
- **Meta** (400, 0.875rem, tabular figures, third ink): dates, counts, authors, trails, currency lines.
- **Label** (italic 400, 0.875rem, third or second ink): margin terms, register column heads, form labels, filter names. Never uppercase, never tracked.
- **Mono** (Source Code Pro, 0.8125rem; 0.875rem in the source view): paths, citation stamps, member ids, settings blocks.

### Named Rules
**The Two Voices Rule.** Charis SIL carries a memory's own words: its text, its summary, and its name wherever it is listed. Cooper Hewitt carries everything else: titles, labels, controls, metadata and tables.

**The Italic Label Rule.** Labels are italic in the regular weight, and the current place is bold italic (the masthead's current item, the contents tree's current leaf). Uppercase tracking is not part of this world.

**The Rank-Not-Hue Rule.** Accepted memory is named in bold; personal memory in regular over a dashed rule and in third ink in the tree; superseded and retired memory is struck through in third ink, superseded with a dagger (†). No colour does this work.

**The Figures Rule.** Counts, dates, times and version numbers take tabular figures.

## Layout

A three-part frame. A sticky 60px masthead band (plus its 4px green foot); below it a 304px contents column on the panel paper, sticky and scrolling on its own, its rule running the full length of the page; then the page, padded 44px 56px 104px.

A memory's page is a two-column reading grid: the text column at the 68ch measure and a 256px margin, 56px apart. The head (trail, title, summary, currency line, status box), the text and the history run down the left; the margin (standing, type, author, relations, cite as, actions) is sticky on the right, ruled off by a hairline on its left. At 1181px and wider, version numbers hang in the gutter to the left of the text column.

Pages share two measures, so the right edge holds from page to page: every single-column page (contents, folders, search, sessions, the team, settings, forms and refusals) is 760px; registers (Challenges, the board, the audit log) take up to 1000px.

Spacing rhythm: 52px above a section heading, 64px above the history, 72px above the colophon; 16 to 24px between items within a section; list rows padded 9 to 17px.

Responsive: at 1180px and below the margin folds under the text into a grid of terms and a one-line standing line appears under the currency line. At 900px and below the contents column leaves the frame (it opens as a drawer), the nav and search collapse into masthead icons, page insets drop to 16px, headline drops to 2rem, facing texts stack and folder heads stop hanging. At 600px and below dot leaders drop and figures wrap under names, and the history slider takes its own row.

### Named Rules
**The Measure Rule.** Memory text never runs wider than 68ch; single-column pages hold to 760px. Wide registers scroll sideways inside their own container, never the page.

**The Hanging Head Rule.** Part heads in a folder hang 18px into the left margin and each level below steps in 18px (12px at 900px and below), so the structure reads from the left edge like a code's numbered divisions.

**The Leader Rule.** A name and its figures are joined by a dotted leader: 1px dotted third ink at 40 to 50% opacity, lifted 5px onto the baseline.

## Elevation & Depth

Flat. Separation is a hairline rule or a step of paper (paper, panel, hover paper). A list opens with a 2px ink rule; parts inside it divide on 1px rules; entries on soft rules.

### Shadow Vocabulary
- **Button edge** (`box-shadow: 0 2px 0 var(--edge)`): GOV.UK's button edge, straight down, in the button's own darker shade (`accent-edge`, `danger-edge`, or `field-edge` for a default button). On press the edge disappears and the button moves down 2px into it. Disabled buttons have no edge.
- **Floating menu** (Mantine shadow `md`): member and row menus, the only things above the page.
- **Status foot** (not a shadow: `border-bottom-width: 4px`): the heavier foot of the status box, the issued slip and a refusal.

### Named Rules
**The Flat Page Rule.** Nothing on the page casts a shadow. The only raised things are a button on its edge and a menu that floats.

## Shapes

Every corner is square: the theme sets every Mantine radius to 0, fields and buttons included. Form comes from rules. A 1px solid rule divides parts, a 1px soft rule divides entries and register rows, a 1px dotted rule draws leaders and cross-reference underlines, a 1px dashed rule marks personal memory, a 2px ink rule opens a list or a register header, a 4px coloured foot sets off the status box and the masthead, and a 4px red top rule sets off the notice on the front page. The wordmark is a 14px green square.

## Components

### Buttons
Solid, square and standing on an edge, as GOV.UK draws them.
- **Shape:** square (0px).
- **Primary:** signal green with white text, weight 600, on a 2px signal edge. Hover deepens to `accent-hover`.
- **Danger:** challenge red on its own darker edge, only to confirm taking something away.
- **Default:** hover-paper fill, ink text, on a field-edge 2px edge; the second choice beside a primary (Reject, Keep it, Pin, Unpin).
- **Press:** the edge disappears and the button drops 2px.
- **Focus:** a 3px yellow outline with a 2px ink inset.
- **Quiet link:** tertiary and take-away actions as underlined text at 0.875rem with a 14px outline icon; green, or red for "Retire it…". Hover thickens the underline to 2px.

### Inputs / Fields
- **Style:** square, white field, a `field-edge` border (4.5:1 on paper). Labels in italic second ink above.
- **Focus:** a 3px yellow outline around a 1px ink inset.
- **Masthead search:** a white field on the band in light, `band-field` in dark.
- **Checkbox:** 2px ink border, filled green with white tick when checked. **Switch:** field-edge track, green when on.

### Navigation
- **Masthead:** the near-black band, 60px, with a 4px Band Green foot; in dark a 1px rule beneath the foot sets the page off from the band. Wordmark (green square, "Shared Memory" 700, the team after a divider), then nav links in second band ink at 0.9375rem/500. Hover draws a 4px band-2 underline; the current page is white, bold italic, with a 4px Band Green underline. Focus fills the item yellow with an ink underline.
- **Contents tree:** 32px rows on the panel, indenting 14px per level, chevrons turning 90 degrees (180ms). Folders carry tallies in third ink; memory leaves are in Charis SIL; personal leaves in third ink; cancelled leaves struck through. The current row takes the signal wash, bold italic. Keyboard focus fills a row yellow with a 3px ink bar.
- **Trail:** 0.875rem links underlined in the rule colour, separated by "›".
- **View switch and filters:** plain text tabs; the selected one is ink, bold, over a 3px ink underline (tabs) or a 3px green underline (filters).

### Status Box (signature)
The one box that says where a memory stands (legislation.gov.uk). A 1px rule in the state's colour, a 4px foot, the state's wash, an 18px outline icon or the dagger, then a bold state word and a sentence. Four states: in force (green), challenged (red), cancelled for superseded and retired (third-ink rule on the panel), and as it stood (amber). Personal memory takes a dashed third-ink rule on white. Only the status box is tinted in a memory's head.

### Currency Line
Under every memory title in meta type: "First written 2 Jun 2026 · Last amended 21 Aug 2026, 10:30 by Olive Owner · 4 versions", the count linking to the history (Justice Laws, GOV.UK, SEP).

### Point-in-Time History (signature)
- **Timeline:** "First written" and the date at the left end, the current standing at the right, and a slider over the versions between. Its fill is green when the current text is shown, third ink when the memory is cancelled, and amber while an earlier version is open, when the right end names "Version 2 of 3" in amber ink.
- **Amendment markup:** with "Mark what this version changed" on, the text as it stood shows insertions and substitutions in bold ink square brackets with a green superscript marker (A1, A2…) and removed words as bold red spaced dots with a red marker. Each marker links to a numbered Amendments list under a rule, in Cooper Hewitt with the quoted words in Charis SIL; the targeted note takes the soft highlight (legislation.gov.uk).
- **Versions:** newest first, under a 2px ink rule. Each row: a 1.625rem bold tabular version number (hanging in the gutter on wide screens), what happened as a bold sentence, then "In force from … to …" with a quiet link to read it. The current row sits on the panel.

### Margin and Citation
The ruled right margin: italic label terms over values, the standing as marks, and "Cite as": the path in Source Code Pro with the version's short commit in bold green, plus a copy button (EUR-Lex). Actions sit below a rule: a default button and a red quiet link.

### State Marks
Inline marks, never pills: 14px outline icon plus word in 0.875rem/500 second ink. Pinned is green 700, Challenged is red 700, Superseded carries the Charis dagger, Retired is the word alone, Restricted a lock. The level ("Project memory") is bold second ink; personal is regular third ink. The waiting count in the masthead is the only filled chip: a 20px red square with white bold tabular figures.

### Table of Contents
Each part between rules (the first under a 2px ink rule), its name in Title type, a dotted leader to its count and last change in tabular meta, a note beneath, then folders indented 22px in 600 and deeper folders in 400 second ink. Hover underlines the name at 2px.

### Notice, Refusal, Issued Slip
The front-page notice: a 4px red top rule, a bold title with the scales icon, and each waiting item on its own soft-ruled line with the memory's name in Charis SIL. A refusal: red rule, 4px foot, red wash, warning icon, the server's own words in ink. An issued token: green rule, 4px foot, green wash, the token in a white mono block. Each arrives with the 220ms appear.

### Facing Texts
A challenge compares the memory now and what is offered in its place side by side in two ruled cells, each in Charis SIL, with Accept (primary) and Reject (default) beneath. They stack at 900px and below.

### Registers
Members and the audit log as full-width tables: italic column heads over a 2px ink rule, rows on soft rules with 12px padding, the primary cell in ink 600, paths in mono, cancelled rows struck.

### Loading
The shape of what is coming: 12px bars of hover paper at 62%, 88% and 44% width, breathing to 45% opacity over 1.6s.

## Do's and Don'ts

### Do:
- **Do** reference colour through the custom properties (`var(--paper)`, `var(--ink-2)`, `var(--accent)`) so both schemes follow, and point framework components at them rather than at the framework's own palette.
- **Do** give every state a mark and a word: the dagger, "Superseded" and a struck title; "Retired" and a struck title; the scales and "Challenged"; the pin and "Pinned"; the lock and "Restricted"; a dashed rule and "Personal memory".
- **Do** pair the yellow focus highlight with ink: an ink inset on fields and controls, an ink bar under links, tree rows and nav items.
- **Do** keep cancelled memory in its place, after current memory, struck through in third ink.
- **Do** set a memory's text in Charis SIL at 1.1875rem and 1.68 within 68ch, exactly as stored, and offer its source file in Source Code Pro beside it.
- **Do** tell history in sentences with closed date ranges, newest first.
- **Do** keep motion to state changes on `cubic-bezier(0.16, 1, 0.3, 1)`: 150ms for nav colour and underlines, 180ms for a folder's chevron, 220ms for a notice or slip to appear (fade and a 4px rise), and honour reduced motion.

### Don't:
- **Don't** build the admin-dashboard arrangement: no sidebar of features, no stat cards, no badge soup. The waiting count on Challenges is the only filled chip.
- **Don't** let colour alone carry a state, or use a hue for anything outside its one meaning.
- **Don't** return to the antique world: no tinted paper, no book greens or oxbloods, no uppercase-tracked labels, no kickers above titles.
- **Don't** round corners, shadow cards, or box content that a rule could separate. The button edge belongs to buttons only.
- **Don't** set text in `past-rule` or `highlight`; they are rule and fill colours.
- **Don't** use a Unicode symbol as an icon. Icons are Tabler outline icons at stroke 1.6, 14 to 18px; the dagger, the amendment brackets and the repeal dots are the only typographic marks, each carrying meaning in the text.
- **Don't** restyle, truncate or paraphrase a memory's words on its own page; summaries belong to lists.
