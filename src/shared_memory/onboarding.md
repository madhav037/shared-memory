# Onboarding

Onboarding imports what this member and this repository already have written down into Shared Memory. You read the sources and cut them into memories; the member approves each one before it is saved, and again before it is promoted. Run the steps in order, and tell the member which step you are on.

## 1. List the sources

Look in three places and show the member every file you found, grouped by place:

- **Repository documents**: `CLAUDE.md`, `AGENTS.md`, the conventions in `README.md`, everything under `docs/`, and ADRs.
- **Your local memory** for this repository on this machine (in Claude Code, this project's memory folder under `~/.claude/projects/`).
- **Other coding agents' rule files**: `.cursorrules`, `.cursor/rules/`, `.github/copilot-instructions.md`, `.github/instructions/`, `GEMINI.md`, `.clinerules`, `.windsurfrules` and the like.

What Shared Memory wrote itself is no source: the section of `AGENTS.md` between the `shared-memory` markers, `.cursor/rules/shared-memory.mdc`, `.agents/skills/shared-memory/` and the other connection files.

Ask the member which files to skip. **Done when** every file found is marked *import* or *skip*, each skip with the member's reason.

## 2. Cut each source into proposals

Read each *import* file in full and cut it into proposals, one thing per memory. A proposal has:

- a **title**, and a one-line **summary** that tells a teammate what it says without opening it;
- a **type**: `convention` (a rule followed every day), `decision` (a choice made once, with its reasons), `architecture` (how the system is built), or `gotcha` (a surprising fact that wastes time);
- a **body** of at most 600 words, keeping the source's own wording;
- a proposed **level**: `project` if everyone on this project follows it, `team` if it holds for every project in the team, `personal` if it is one member's note that teammates may still want to read;
- its **source**, written `repository:path` for a file in this repository, using the repository name this session is connected with;
- its **writer**, found as below.

**The writer.** For a source in git, run `git blame --line-porcelain -L <start>,<end> -- <file>` over the lines the proposal was cut from. When one person wrote every line, they are the writer: find their GitHub username from a noreply address (`<id>+<username>@users.noreply.github.com`) or with `gh api repos/<owner>/<repository>/commits/<sha> --jq .author.login`. Lines by several people, a username you can't find, or a source outside git (your local memory, an untracked file) have no single writer: this member will be the author, and you keep the original writer's name where one is known.

**Leave out**, and keep a note of each with its reason:

- what the environment already states: commands in `package.json`, a `Makefile` or CI, the directory layout, anything one lookup answers;
- stale notes: check each claim against the code as it is now, and leave out what no longer holds;
- this member's own preferences and how their machine is set up, which stay in local memory;
- secrets. Describe where a secret is kept instead; the server refuses a memory that looks like it holds one;
- what Shared Memory already says: `search` for each proposal first.

**Done when** every *import* file is accounted for passage by passage: each passage is in a proposal or noted as left out with its reason.

## 3. Have the member approve, ten at a time

Show the proposals in batches of ten, as a table: title, type, summary, proposed level, source, writer. After each batch, list what you left out of those sources and why. The member approves, changes or drops each proposal, and may bring back something left out. The choice is theirs: wait for it.

**Done when** every proposal is approved, or dropped by the member.

## 4. Save each approved proposal as personal memory

Call `remember` for each approved proposal; every one lands first as this member's personal memory, whatever its level will be. Where this member will be the author and the original writer's name is known, end the body with `Originally written by <name> (<source>).` If a save is refused, fix what the refusal names and save again, or tell the member why it can't be saved.

**Done when** every approved proposal has a memory path, or a refusal the member has been told about.

## 5. Promote what the member approved, one at a time

Take the memories approved for `project` or `team` level in turn, and finish each `promote` before starting the next, so the similar-memory check runs on every one.

- **A single writer with a GitHub username**: call `promote` with `author="@<username>"` and `imported_from="<source>"`. That member becomes the author, this member is recorded as its importer, and the author is told in their next briefing. If the server answers that they are not a member or can't reach this project, add the `Originally written by` line with `edit_memory` and promote without `author` and `imported_from`.
- **No single writer**: call `promote` with the path and level alone.
- **`similar_memories` comes back**: judge whether each similar memory contradicts this one, show the member each with your judgement, and call `promote` again with the `reference` and their `resolutions`. A memory that turns out to repeat an existing one is `cancel`; offer to `delete_memory` it.
- **`challenge_raised` comes back**: tell the member whose decision it waits on. The memory stays personal until then.

**Done when** every memory approved for project or team level is promoted, waiting on a challenge, or cancelled on the member's word.

## 6. Report

Tell the member what was promoted to project and to team memory and in whose name, what stays personal, what waits on a challenge, and what was left out and why. Onboarding changes no file in the repository or in your local memory. A memory that turns out wrong is put right the usual way: `retire` it, or promote one that supersedes it.
