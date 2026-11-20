# Onboarding

Onboarding imports what this member, this project's repositories and their team already have written down into Shared Memory. You read the sources and cut them into memories; the member approves each one before it is saved, and again before it is promoted. Run the steps in order, and tell the member which step you are on. Everything runs here, in this session: nothing is sent anywhere but this team's Shared Memory server.

Read the progress so far first: the section at the end of these steps lists each repository and kind of outside source an earlier run recorded, with its status. Tell the member what is already done and skip it unless they ask to run it again.

## 1. Choose this run's sources

**Which repositories.** Ask the member which checkouts on this machine to onboard: this one, and any other repository of this project they name. One run can walk several checkouts and keeps one list of proposals for the project across them; give each its repository name as the project lists it.

**Which sources.** List every source you can reach for those repositories, grouped by kind, and ask the member which to use this run. Say that a big run spends the member's own tokens, so they can start small:

- **Repository documents**: `CLAUDE.md`, `AGENTS.md`, the conventions in `README.md`, everything under `docs/`, and ADRs.
- **Your local memory** for each repository on this machine (in Claude Code, this project's memory folder under `~/.claude/projects/`).
- **Other coding agents' rule files**: `.cursorrules`, `.cursor/rules/`, `.github/copilot-instructions.md`, `.github/instructions/`, `GEMINI.md`, `.clinerules`, `.windsurfrules` and the like.
- **Git history**: commit messages that give a reason, reverts, and patterns removed and why (`git log --grep`, `git log -S`, the messages of `revert` commits). "We removed X because Y" is a memory worth keeping.
- **A scan of the code**: the conventions the code actually follows and the existing utilities agents keep duplicating (shared helpers, wrappers, base classes), each proposal naming the file it describes.
- **Outside sources**: wiki or doc exports (Confluence, Notion, SharePoint, runbooks, knowledge-transfer documents), tickets, and pull request review comments the reviewers keep repeating. Reach each with a tool you already have, `gh` or `glab` for tickets and review comments, an Atlassian or Notion MCP server for a wiki; without one, ask the member for an exported folder and read that. Tell the member which outside sources you couldn't reach and why.

What Shared Memory wrote itself is no source: the section of `AGENTS.md` between the `shared-memory` markers, `.cursor/rules/shared-memory.mdc`, `.agents/skills/shared-memory/` and the other connection files.

**Done when** the member has chosen the repositories and sources for this run, and every file or outside source found is marked *import* or *skip*, each skip with the member's reason.

## 2. Cut each source into proposals

Read each *import* source in full and cut it into proposals, one thing per memory. A proposal has:

- a **title**, and a one-line **summary** that tells a teammate what it says without opening it;
- a **type**: `convention` (a rule followed every day), `decision` (a choice made once, with its reasons), `architecture` (how the system is built), or `gotcha` (a surprising fact that wastes time);
- a **body** of at most 600 words, keeping the source's own wording;
- a proposed **level**: `project` if everyone on this project follows it, `team` if it holds for every project in the team, `personal` if it is one member's note that teammates may still want to read;
- its **source**, named precisely enough that a teammate can check it: `repository:path` for a file in a repository, using the repository name your briefing gives for this one (its last line: "It works in the repository ....") or the name the project lists for another checkout; `commit:repository@revision` for a commit; `wiki:<page>` for a wiki or doc export page; `ticket:<reference>` for a ticket; `pr-comment:<reference>` for a pull request review comment (`pr-comment:billing-api#88`); or `interview:<reference>` for an interview;
- its **writer**, found as below.

**The writer.** For a source in git, run `git blame --line-porcelain -L <start>,<end> -- <file>` over the lines the proposal was cut from. When one person wrote every line, they are the writer: find their GitHub username from a noreply address (`<id>+<username>@users.noreply.github.com`) or with `gh api repos/<owner>/<repository>/commits/<sha> --jq .author.login`. For a commit, its author is the writer. For an outside source, the writer is whoever the source names (the page's author, the ticket's reporter, the reviewer), as a GitHub username where you can find one. Lines by several people, a username you can't find, or a source with no writer named (your local memory, an untracked file) have no single writer: this member will be the author, and you keep the original writer's name where one is known.

**Leave out**, from every source, and keep a note of each with its reason:

- what the environment already states: commands in `package.json`, a `Makefile` or CI, the directory layout, anything one lookup answers;
- stale notes: check each claim against the code as it is now, and leave out what no longer holds (old wiki pages and tickets often describe code that has gone);
- this member's own preferences and how their machine is set up, which stay in local memory;
- secrets. Describe where a secret is kept instead; the server refuses a memory that looks like it holds one;
- what Shared Memory already says: `search` for each proposal first.

**Repeated rules.** Across several repositories and sources the same rule turns up again and again. An identical rule found in many places becomes one proposal, listing every source; propose it at `project` level, or `team` level when it holds across the team's projects (the member says which). Where variants of a rule disagree, don't pick one: show the variants side by side, with their sources, and have the member settle which holds, or that each stays in its own repository, before anything is saved.

**Done when** every *import* source is accounted for passage by passage: each passage is in a proposal or noted as left out with its reason, and every repeated rule is one proposal.

## 3. Have the member approve, source by source

Show the proposals source by source, as a table: title, type, summary, proposed level, source, writer, at most ten rows at a time. After each table, list what you left out of that source and why. The member approves, changes or drops each proposal, and may bring back something left out. Once they have read a source's tables, they may approve all of one source's proposals in one step; they can still change, drop or bring back any one of them first. The choice is theirs: wait for it.

**Done when** every proposal is approved, or dropped by the member.

## 4. Save each approved proposal as personal memory

Call `remember` for each approved proposal; every one lands first as this member's personal memory, whatever its level will be. Where this member will be the author and the original writer's name is known, end the body with `Originally written by <name> (<source>).` If a save is refused, fix what the refusal names and save again, or tell the member why it can't be saved.

**Done when** every approved proposal has a memory path, or a refusal the member has been told about.

## 5. Map repository documents onto foundations

A project's **foundations** hold its sources of truth: `architecture`, `product`, `glossary` and `decisions`, and any extra a project lead added (the briefing's foundations line names them). Map each approved repository-document proposal bound for `project` level onto one, and show the member the mapping:

- `ARCHITECTURE.md` and the like: `architecture`. ADRs and `docs/adr/`: `decisions`. `PRODUCT.md` and a vision or requirements document: `product`. `CONTEXT.md` or a glossary: `glossary`. A document that fits no foundation stays a plain project memory.
- The `architecture` foundation takes only `architecture` memories, and `decisions` only `decision` memories; the others take any type except a known issue, so retype a proposal that doesn't fit, with the member's say.

**Done when** every such proposal has a foundation or is marked as plain project memory.

## 6. Promote what the member approved, one at a time

Take the memories approved for `project` or `team` level in turn, one at a time, and finish each `promote` before starting the next, so the similar-memory check runs on every one, even those the member approved a whole source at once.

- **A single writer with a GitHub username**: call `promote` with `author="@<username>"` and `imported_from="<source>"`. That member becomes the author, this member is recorded as its importer, and the author is told in their next briefing. If the server answers that they are not a member or can't reach this project, add the `Originally written by` line with `edit_memory` and promote without `author` and `imported_from`.
- **No single writer**: call `promote` with the path and level alone.
- **A foundation was mapped**: also pass `foundation` on every call of that promotion; an `architecture` or `decision` memory goes to its foundation without it.
- **`similar_memories` comes back**: judge whether each similar memory contradicts this one, show the member each with your judgement, and call `promote` again with the `reference` and their `resolutions`. A memory that turns out to repeat an existing one is `cancel`; offer to `delete_memory` it.
- **`challenge_raised` comes back**: tell the member whose decision it waits on. The memory stays personal until then. A member who is neither a keeper of the foundation nor a project lead always gets one for a foundation, a foundation challenge a keeper or lead decides.

**Done when** every memory approved for project or team level is promoted, waiting on a challenge, or cancelled on the member's word.

## 7. Replace imported files with pointers

Once a repository document's passages are all in a foundation, its file duplicates it and will drift. This holds for a file in any checkout this run walked. **Ask the member first**, listing each file you would replace, and change nothing without their yes. Where they agree, replace the file's whole content with a short pointer, in this wording:

> This document now lives in Shared Memory, in the `<foundation>` foundation of the project `<project>`. Read it with Shared Memory: `read` the foundation's index (`projects/<project>/shared/foundations/<foundation>/index.md`) or `search` for it; the briefing names the foundations. Edit it there, not here.

Leave a file alone when any of its passages is still waiting on a foundation challenge or was left out: the pointer would hide what is not yet in the foundation. **Done when** every file the member agreed to is replaced, and the rest are listed with the reason.

## 8. Record progress and report

Call `record_onboarding_progress` once for each repository and each kind of outside source (`wiki`, `ticket`, `pr-comment`, `interview`) this run read: `status` is `done` when every proposal from it is promoted, waiting on a challenge, dropped or left out, `partly_done` when some are not yet, and `left_out` is how many passages of it you left out. Record a repository with `repository`, an outside source with `outside_source`. The project's leads see it in project settings, and the next run reads it.

Cover every repository and source this run read, one part each, and the outside sources you couldn't reach. Tell the member what was promoted to project and to team memory and to which foundation and in whose name, what stays personal, what waits on a challenge, and what was left out and why. Onboarding changes no file in any repository or in your local memory, except the pointers the member approved in step 7. A memory that turns out wrong is put right the usual way: `retire` it, or promote one that supersedes it.
