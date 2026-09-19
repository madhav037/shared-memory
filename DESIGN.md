---
name: Shared Memory
description: The team's memory published like a consolidated code of practice, in paper, ink and one buckram-green binding.
colors:
  paper: "#f7f8f6"
  paper-2: "#eef1ee"
  paper-3: "#e4e9e5"
  ink: "#17211c"
  ink-2: "#44544b"
  ink-3: "#5d6d64"
  rule: "#cdd5cf"
  rule-soft: "#dfe5e0"
  accent: "#1e5b46"
  accent-hover: "#154a39"
  accent-ink: "#f7f8f6"
  accent-wash: "#e1ebe5"
  insert-wash: "#d7e8dd"
  danger: "#9b2c1f"
  danger-hover: "#7f2419"
  danger-wash: "#f5e4e0"
  selection: "#c9dfd2"
  paper-dark: "#101814"
  paper-2-dark: "#0b120f"
  paper-3-dark: "#18221d"
  ink-dark: "#e4ebe6"
  ink-2-dark: "#b4c1b9"
  ink-3-dark: "#93a39a"
  rule-dark: "#2b3831"
  rule-soft-dark: "#1f2a24"
  accent-dark: "#7cc4a0"
  accent-hover-dark: "#93d3b3"
  accent-ink-dark: "#0b120f"
  accent-wash-dark: "#16291f"
  insert-wash-dark: "#1d3a2b"
  danger-dark: "#ec8a76"
  danger-hover-dark: "#f2a292"
  danger-wash-dark: "#2e1814"
  selection-dark: "#24493a"
typography:
  display:
    fontFamily: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif'
    fontSize: "3rem"
    fontWeight: 640
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  headline:
    fontFamily: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif'
    fontSize: "2.125rem"
    fontWeight: 620
    lineHeight: 1.12
    letterSpacing: "-0.015em"
  title:
    fontFamily: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif'
    fontSize: "1.3125rem"
    fontWeight: 620
    lineHeight: 1.25
    letterSpacing: "-0.005em"
  standfirst:
    fontFamily: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif'
    fontSize: "1.1875rem"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif'
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.65
    fontFeature: '"onum", "pnum"'
  memory-name:
    fontFamily: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif'
    fontSize: "1.125rem"
    fontWeight: 620
    lineHeight: 1.3
  ui:
    fontFamily: '"Public Sans Variable", "Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
  control:
    fontFamily: '"Public Sans Variable", "Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1
  meta:
    fontFamily: '"Public Sans Variable", "Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: '"tnum"'
  label:
    fontFamily: '"Public Sans Variable", "Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "0.6875rem"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "0.07em"
  mono:
    fontFamily: 'ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, monospace'
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  square: "0px"
  slight: "2px"
spacing:
  inline: "6px"
  control: "12px"
  line: "16px"
  block: "22px"
  set-off: "28px"
  section: "44px"
  page-top: "36px"
  page-inset: "48px"
  page-inset-phone: "16px"
  gutter: "56px"
  masthead: "56px"
  contents: "304px"
  margin-note: "248px"
  measure: "68ch"
  column: "72ch"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.control}"
    rounded: "{rounded.square}"
    height: "36px"
    padding: "0 18px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-default:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.square}"
    height: "36px"
    padding: "0 18px"
  button-default-hover:
    backgroundColor: "{colors.paper-3}"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.control}"
    rounded: "{rounded.square}"
    height: "30px"
    padding: "0 14px"
  button-danger-hover:
    backgroundColor: "{colors.danger-hover}"
  quiet-link:
    textColor: "{colors.accent}"
    typography: "{typography.meta}"
  quiet-link-danger:
    textColor: "{colors.danger}"
    typography: "{typography.meta}"
  input:
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.square}"
    height: "36px"
  nav-link:
    textColor: "{colors.ink-2}"
    typography: "{typography.ui}"
    height: "{spacing.masthead}"
    padding: "0 10px"
  nav-link-current:
    textColor: "{colors.ink}"
  waiting-count:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.square}"
    height: "18px"
    padding: "0 5px"
  contents-column:
    backgroundColor: "{colors.paper-2}"
    width: "{spacing.contents}"
  tree-row:
    textColor: "{colors.ink-2}"
    typography: "{typography.ui}"
    height: "30px"
    padding: "0 14px 0 12px"
  tree-row-hover:
    backgroundColor: "{colors.paper-3}"
    textColor: "{colors.ink}"
  tree-row-current:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
  banner:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink-2}"
    typography: "{typography.ui}"
    rounded: "{rounded.square}"
    padding: "12px 14px"
  refusal:
    backgroundColor: "{colors.danger-wash}"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.square}"
    padding: "12px 14px"
  issued-slip:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.square}"
    padding: "16px 18px"
  as-it-stood:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    padding: "10px 14px"
  source-view:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    typography: "{typography.mono}"
    rounded: "{rounded.square}"
    padding: "18px 20px"
  margin-note:
    textColor: "{colors.ink-2}"
    typography: "{typography.meta}"
    width: "{spacing.margin-note}"
  memory-text:
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    width: "{spacing.measure}"
  history-insert:
    backgroundColor: "{colors.insert-wash}"
    textColor: "{colors.ink}"
---

# Design System: Shared Memory

## Overview

**Creative North Star: "The Consolidated Code"**

The console publishes the team's memory the way a consolidated code of practice is published: a contents of everything a member can reach, each memory set as a citable section, and its standing, author and history annotated in a ruled margin. Light is the printed page; dark is the bound volume. Paper and ink carry nearly everything, and a single buckram green is the binding: it draws the rules that set things off, marks the current place, and carries links and primary actions.

The density is that of a reference book, not a dashboard. A slim masthead, a contents column in a slightly deeper paper, and a reading column held to a book measure. Weight is carried by typographic rank (serif against sans, upright against italic, whole against struck through), never by colour fields, cards or badges. Hairline rules, dot leaders and heads hanging into the margin do the structural work that boxes and shadows do elsewhere.

The system refuses the admin-dashboard arrangement: no sidebar of features, no stat cards, no badge soup. Nothing disappears; superseded and retired memory keeps its place, visibly cancelled. Motion is limited to state changes on one soft ease-out, and reduced motion is honoured.

**Key Characteristics:**
- Paper and ink in two bindings, the printed page (light) and the bound volume (dark), both tinted toward green and never neutral grey.
- One structural accent, buckram green, for rules, the current place, links and primary actions.
- Source Serif 4 for what is read, Public Sans for what is operated, the system monospace for paths and source.
- Square corners, hairline rules, dot leaders, part heads hanging into the margin.
- State is a mark and a word; the weight of a memory is type rank.
- Flat: depth comes from steps of paper and from rules, not from shadow.

## Colors

A green-tinted paper-and-ink palette in two bindings, with one buckram green and one oxide red. Every value lives as a CSS custom property on the root (`--paper`, `--ink-2`, `--accent` and so on), is redefined under the dark scheme with the same name, and Mantine's own variables are pointed at these properties. The `-dark` keys above are the dark-scheme values of the same properties.

### Primary
- **Buckram Green** (accent; accent-dark in the bound volume): the binding colour. It draws the 2px rule above a notice and the title page, the 2px underline under the current nav link, tab and pressed filter, links, the focus outline and the caret; it fills the primary button and the waiting count. Hover deepens it on the printed page (accent-hover) and lifts it in the bound volume (accent-hover-dark).
- **Binding Wash** (accent-wash): the only surface the green tints. It marks the current row of the contents, the selected version in the history ledger, the strip that says a memory is shown as it stood, and the slip holding a newly issued token.
- **Insertion Wash** (insert-wash): sits behind words a version or an offer inserted, always with a 2px buckram underline.
- **Accent Ink** (accent-ink): text on a filled green or red: the paper colour in light, the deepest cloth in dark.

### Secondary
- **Oxide Red** (danger): refusals from the server, the challenged mark, and actions that take something away (retire, take access away, remove a lead, forget a repository, remove a member). Its hover deepens (danger-hover) in light and lifts in dark.
- **Oxide Wash** (danger-wash): the background of a refusal block only, inside a 1px oxide border.

### Neutral
- **Printed Paper / Cloth** (paper): the page itself.
- **Contents Paper** (paper-2): the contents column, banners, the source view, code blocks and settings blocks. In the bound volume it is darker than the page, so the contents column recedes like a set-in column.
- **Hover Paper** (paper-3): hovered rows, inline code, the default button's hover, disabled controls and loading bars.
- **Ink** (ink): titles, memory text, the current nav link, register primary cells.
- **Second Ink** (ink-2): standfirsts, summaries, notes, nav links at rest, the margin's values.
- **Third Ink** (ink-3): metadata, labels, counts, trails, placeholders, cancelled titles.
- **Rule** (rule): hairlines between parts, the masthead and contents edges, banner borders, slider track.
- **Soft Rule** (rule-soft): between entries, lines and register rows.
- **Selection** (selection): selected text, set with ink.

### Named Rules
**The Binding Rule.** Buckram green is the binding, not a paint: it draws rules, marks the current place and carries links and primary actions. It fills nothing larger than a button or the waiting count; the only green surfaces are the pale washes that mark where you are, what was inserted, or a token just issued.

**The Mark-and-Word Rule.** State is a mark and a word, never a hue alone. Red never appears without an icon and a sentence, and green never signals a status by itself.

**The Third-Ink Rule.** Third ink is for text on paper and paper-2 only (5.1:1 and 4.8:1 on the printed page). On paper-3 or a wash it falls under 4.5:1, so text set on those steps up to second ink.

## Typography

**Display Font:** Source Serif 4 Variable (with Georgia, serif), optical sizes on
**Body Font:** Source Serif 4 for memory text; Public Sans Variable (with ui-sans-serif, system-ui, sans-serif) for every control, label and piece of metadata
**Label/Mono Font:** Public Sans for labels; the system monospace (ui-monospace, Cascadia Mono, SF Mono, Menlo, Consolas) for paths and the file as Claude reads it

**Character:** A government-publication grotesk against a text serif with optical sizes. The sans is the apparatus of the code (contents, margin terms, controls, registers); the serif is the code itself, and also every name and heading that the reader navigates by.

### Hierarchy
- **Display** (640, 3rem, 1.05, -0.02em): the title page only, before sign-in and when the server can't be reached. 2.25rem at 900px and below.
- **Headline** (620, 2.125rem, 1.12, -0.015em): one page title per page, balanced, held to 28ch unless it is a single word. 1.75rem at 900px and below.
- **Title** (620, 1.3125rem, 1.25): section headings, part names in the table of contents, a disputed memory's name, second-level headings inside memory text.
- **Standfirst** (400, 1.1875rem, 1.5): the serif paragraph under every page title, in second ink, held to 58ch.
- **Body** (400, 1.125rem, 1.65): memory text, at a 68ch measure, with oldstyle proportional figures and hanging punctuation. History and challenge texts use the same face at 1.0625rem and 0.9875rem.
- **Memory name** (620, 1.125rem, 1.3): a memory's name in lists, results and pins; folder lines set it at 1.03rem and 600. Serif summaries sit under it at 0.9375 to 0.9875rem in second ink.
- **UI** (400 to 550, 0.875rem, 1.55): nav, notices, banners, register cells, form labels.
- **Control** (600, 0.875rem): button text.
- **Meta** (400, 0.8125rem): dates, counts, authors, trails and margin values, with tabular figures.
- **Label** (650, 0.6875rem, 0.07em, uppercase): margin terms and table column heads. A 0.75rem cut at 0.06em names the contents column and small sub-sections such as "In every briefing".
- **Mono** (400, 0.8125rem, 1.6): the source view; paths drop to 0.75rem in the margin and the audit log.

### Named Rules
**The Two Voices Rule.** The serif carries what is read: memory text, the names of memories, folders and parts, page titles, standfirsts and the wordmark. The sans carries what is operated: controls, labels, metadata and tables. A memory's name is serif wherever it appears, even as a leaf in the contents column.

**The Rank-Not-Hue Rule.** A memory's weight is set in type. Accepted memory is upright at 620; personal memory is italic at 450 over a dashed rule; superseded and retired memory is struck through at 450 in third ink. No colour does this work.

**The Figures Rule.** Counts, dates and times take tabular figures; figures inside memory text are oldstyle and proportional.

## Layout

The frame is a sticky 56px masthead over a two-column grid: a 304px contents column and a fluid page. The contents column is sticky, scrolls on its own, sits in contents paper, and its paper and right-hand rule are painted into the frame's background so they run the full length of any page. Pages pad 36px at the top, 48px at the sides and 96px at the foot.

Widths are measures, not grids: memory text runs at 68ch; the front page, folders, search and the team read in a 72ch column; forms such as the personal token take a 760px narrow width and challenges and project settings a 980px medium width. A memory's page is a two-column reading spread: the text column at 68ch and a 248px margin, 56px apart, the margin sticky 28px under the masthead, with the history below the text.

Spacing is a rhythm rather than a strict scale. The recurring steps are 6px between marks and trail steps, 12px between controls, 16px for form lines and list rows, 22px from a view switch or timeline to the text it controls, 28px to set off a notice, 44px above a section heading and 56px before the history.

Responsive behaviour steps down three times. At 1180px and below the margin folds under the text as a ruled strip whose terms flow in 180px columns, and a one-line standing (level, status, type, author) appears under the standfirst. At 900px and below the contents column leaves the frame and opens as a drawer (88% wide, contents paper) from a masthead icon; the nav and masthead search collapse into a search icon and the member menu; pages pad 24px, 16px and 72px; facing columns stack. At 600px and below the dot leaders drop and each line's figures wrap under its name.

### Named Rules
**The Measure Rule.** Memory text never runs wider than 68ch, and lists of contents read at 72ch. Wide registers scroll sideways inside their own container, never the page.

**The Hanging Head Rule.** Part heads in a folder hang 18px into the left margin, and every level below steps in 18px (12px at 900px and below), so the structure reads from the left edge like a code's numbered divisions.

**The Leader Rule.** A name and its figures are joined by a dotted leader (1px dotted third ink at 45 to 60% opacity, lifted 4px onto the baseline). Under 600px the leader drops and the figures wrap beneath the name.

## Elevation & Depth

The system is flat. Depth is carried by three steps of paper (the page, contents paper for the contents column and set-off blocks, hover paper for hovered rows) and by hairline rules. In the bound volume contents paper is darker than the page, so the contents column recedes rather than rises. The only element that casts a shadow is a menu floating above the page, which takes the framework's small shadow; the contents drawer on small screens sits over a dimmed overlay instead.

### Shadow Vocabulary
- **Floating menu** (`box-shadow: 0 1px 3px rgba(0,0,0,0.05), rgba(0,0,0,0.05) 0 10px 15px -5px, rgba(0,0,0,0.04) 0 7px 7px -5px`): the member menu and the team register's row menus, and nothing else.

### Named Rules
**The Flat Page Rule.** Nothing on the page casts a shadow. Separation is a hairline rule or a step of paper; a shadow is reserved for a menu that floats above the page.

## Shapes

Every corner is square. The Mantine radius scale is compressed to 0 to 2px, and every component the console styles is set to 0, so framework parts that insist on a radius (the slider's thumb) stay effectively square. Forms are rectangles and ruled lines; blocks are set off by a single border, never by rounding or fill alone. Icons are Tabler outline icons at a 1.6 stroke (1.8 at 13 to 14px inside the contents), 14px beside marks and links, 16px in banners and 20px in the masthead on small screens.

### Named Rules
**The Square Corner Rule.** Every corner is square. A framework part that insists on a radius gets no more than 2px.

**The Line Weights Rule.** A 1px solid rule divides parts; a 1px dotted rule divides items within a set and draws leaders; a 1px dashed rule marks personal memory the team hasn't accepted; a 2px buckram rule sets off a notice or the title page and underlines the current place; a 1px ink rule closes a register's header.

## Components

### Buttons
Plain and decisive: square blocks with a clear verb and, where it helps, a 14 to 18px outline icon on the left.
- **Shape:** square corners (0px).
- **Primary:** buckram fill with accent-ink text in 600 Public Sans at 0.875rem; 36px tall with 18px sides by default, 30px with 14px sides in the margin, 42px with 22px sides for sign-in and search.
- **Hover / Focus:** hover deepens to accent-hover (lifts in dark); focus draws a 2px buckram outline 2px outside the button.
- **Default:** paper fill, 1px rule border, ink text; hover steps to hover paper. Used for the second choice (Reject: keep it as it is, Keep it, Unpin, Pin into every briefing, Connect a repository).
- **Danger:** oxide fill with accent-ink text, used only to confirm something being taken away (Retire it), after a quiet link has opened the confirmation.
- **Disabled:** hover paper fill, third-ink text.
- **Quiet link:** a bare text button in buckram at 0.8125rem with a 14px icon and a 5px gap, underlined on hover; the danger variant is oxide. It carries tertiary and destructive-first actions (Retire it…, Take access away, Project settings, Back to the current text).

### Marks and the waiting count
- **Style:** a mark is an inline 14px outline icon and a word at 0.8125rem, 500, second ink, 4px apart. The strong variant (Pinned, You lead) is buckram at 600; the alert variant (Challenged) is oxide at 600. In the contents column a mark may stand as a 13px icon alone, because the row's accessible name carries the word.
- **Level:** accepted levels are named in the label style at 0.75rem (TEAM MEMORY, PROJECT MEMORY), set after the name or in the margin; personal memory drops the capitals into italic sentence case at 500.
- **Superseded:** a dagger (†) in the serif at 600 in third ink, set before a struck title and beside the word Superseded.
- **Waiting count:** an 18px square block of buckram with accent-ink figures (0.75rem, 600, tabular), on the Challenges nav link only.

### Containers
- **Corner Style:** square.
- **Notice:** no box. A 2px buckram rule on top, a 0.9375rem sans title at 650 with the scales icon, items divided by dotted rules with memory names in the serif at 600. Challenges waiting for the member arrive this way at the head of the front page.
- **Banner:** a 1px rule border on contents paper, 12px by 14px padding, a 16px icon and a bold lead word (Superseded., Retired., Challenged., Personal memory of…). The personal-memory banner's border is dashed.
- **Refusal:** a 1px oxide border on oxide wash, ink text, the alert-triangle icon in oxide; it states the server's refusal in its own words.
- **Issued slip:** a 1px buckram border on the binding wash, 16px by 18px padding, the new token in a mono field on paper; shown once.
- **Source and settings blocks:** contents paper, 1px rule, the monospace; the header lines of a memory file in third ink.
- **Empty state:** no box and no illustration: rules above and below, 22px padding, second ink at 0.9375rem, held to 62ch, saying what arrives here and how.
- **Shadow Strategy:** none (see Elevation & Depth).

### Inputs / Fields
- **Style:** Mantine text inputs and selects, square, 36px (42px on the search page), a 1px border, a 15 to 16px search icon inside the masthead and search fields; labels above in the sans.
- **Form line:** fields and their button sit on one band, ruled above and below, with 16px vertical padding, 12px gaps, bottom-aligned.
- **Focus:** the border turns buckram and the 2px buckram outline appears.
- **Error / Disabled:** errors take oxide red; disabled fields take hover paper with third ink.

### Navigation
- **Masthead:** 56px, sticky, paper with a bottom rule. The wordmark "Shared Memory" is serif at 650 and 1.1875rem with the team's name beside it in meta third ink. Nav links are sans at 0.875rem and 500 in second ink, full height with 10px sides; the current link turns ink over a 2px buckram underline that sits on the masthead rule; colour and underline change in 150ms. A 280px search field and the member menu (name and chevron) close the row. The member menu, 260px and square, holds the personal token, appearance (Match this computer, Printed page, Bound volume) and sign out.
- **Contents tree:** rows at least 30px tall in second-ink sans at 0.875rem, indented 14px per level, a chevron that turns 90 degrees in 180ms, and a tally in third ink on the right. Top-level rows are ink at 600; memory leaves are serif at 0.9375rem (italic when personal, struck when cancelled). Hover is hover paper; the current row is the binding wash at 600; keyboard focus is a 2px buckram outline drawn inside the row. It is a full ARIA tree with arrow-key, Home and End movement.
- **Trail:** every folder above the page as a link, 0.8125rem, second ink, separated by slashes in rule colour; hover turns buckram and underlines.
- **View switch:** text tabs at 0.875rem and 500 in third ink on a 1px rule; the selected tab is ink over a 2px buckram underline.
- **Filters:** a 600 third-ink label, then bare text options; the pressed option is ink at 650 over a 1px buckram underline.
- **Mobile:** a contents icon opens the drawer at the left of the masthead; a search icon and a menu icon on the right; nav links move into the member menu.

### Table of contents line (signature)
A name, a dotted leader and its figures (count and last change, separated by a middle dot). Parts sit between 1px rules with the name in the serif at 1.3125rem and 620, a one-line sans note under it (who leads it, what it holds), then its folders at 0.9375rem indented 22px per level. Hovering a line turns its name buckram and underlines it.

### The margin (signature)
A 248px aside with a left hairline and 20px of padding, sticky 28px under the masthead, set as a definition list: terms in the label style (Standing, Type, Author, History, Path), values in meta second ink, paths in the monospace at 0.75rem with a copy button, links in buckram. Actions sit below a rule with a line of 0.75rem help. At 1180px and below it becomes a ruled strip under the text.

### Point-in-time history (signature)
A slider over the memory's versions sits under the view switch, between the first date and "Now" or "Version n of m", with its track and marks in rule colour on paper. Moving it resets the text in place as it stood: a strip in the binding wash inside a buckram border names the date, the change and its author and offers "Back to the current text"; insertions are underlined 2px in buckram on the insertion wash, deletions struck through at 1.5px in third ink, and a switch can turn the marking off. Below the text, the ledger lists every version newest first, 0.8125rem with label-style heads, the selected row in the binding wash and each change a buckram text button.

### Facing pages (signature)
A challenge sets the memory as it stands and what is offered in its place side by side, in one ruled box split by a hairline, each with a serif name, a meta byline and serif text with the offer's changes marked as in the history. Accept (primary) and reject (default) sit beneath. The columns stack at 900px and below.

### Registers
Full-width tables at 0.875rem with tabular figures: heads in the label style over a 1px ink rule, rows on soft rules with 11px of vertical padding, the row's primary cell in ink at 550; cancelled rows go third ink and struck through. Members and the audit log are registers; the history ledger is a lighter variant.

### Loading
The shape of what is coming, never a spinner: 12px bars at 62%, 88% and 44% widths, shimmering from hover paper to contents paper in 1.4s.

### Title page
Before sign-in: a 560px block, centred in the viewport under a 2px buckram rule, the display title, a serif lede in second ink, one primary action (Sign in with GitHub) and fine print in meta third ink.

## Do's and Don'ts

### Do:
- **Do** reference colour through the custom properties (`var(--paper)`, `var(--ink-2)`, `var(--accent)`) so both bindings follow, and point framework components at them rather than at the framework's own palette.
- **Do** set memory text in Source Serif 4 at 1.125rem and 1.65 within 68ch, exactly as stored.
- **Do** give every state a mark and a word: a dagger, "Superseded" and a struck title; "Retired" and a struck title; the scales icon and "Challenged"; the pin and "Pinned"; the lock and "Restricted"; italic, a dashed rule and a banner for personal memory.
- **Do** keep cancelled memory in its place, after current memory, struck through in third ink.
- **Do** join a name to its figures with a dotted leader and set counts and dates in tabular figures.
- **Do** show loading as the shape of what is coming, in shimmering bars of paper.
- **Do** keep motion to state changes on `cubic-bezier(0.16, 1, 0.3, 1)`: 150ms for colour and underlines, 180ms for a folder's chevron, 220ms for a notice or slip to appear (fade and a 4px rise), and honour reduced motion.

### Don't:
- **Don't** build the admin-dashboard arrangement: no sidebar of features, no stat cards, no badge soup. The waiting count on Challenges is the only filled chip.
- **Don't** let colour alone carry a state, and don't use oxide red for anything but refusals, challenges and actions that take something away.
- **Don't** round corners, add shadows to cards, or box content that a rule could separate.
- **Don't** use neutral greys: every paper, ink and rule leans green (OKLCH hue roughly 130 to 170).
- **Don't** set the uppercase label style above a title as a kicker; labels name data (margin terms, table columns, the contents column), they never announce a heading.
- **Don't** use a Unicode symbol as an icon. Icons are drawn outline icons; the dagger is the one typographic mark, set in the serif beside a struck title and the word Superseded.
- **Don't** restyle, truncate or paraphrase a memory's words on its own page; summaries belong to lists.
