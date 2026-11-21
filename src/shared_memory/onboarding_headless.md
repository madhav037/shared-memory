# Onboarding, headless

This run is headless: it runs in CI, or anywhere without a member at the terminal, for one repository. No one is here to approve, so it saves nothing. It reads the repository's sources, cuts them into proposals and writes them to a proposals file, which a member later loads into an interactive onboarding session to approve and promote (ADR-0030). Everything runs here: nothing is sent anywhere but this company's Shared Memory server, and the only call to it that changes anything is recording progress.

**Save nothing.** Never call `remember`, `promote`, `edit_memory`, `delete_memory`, `retire` or any other tool that saves or changes memory, and change no file in the repository except the proposals file.

## 1. Read the sources

Read the progress so far at the end of these steps, and skip this repository if it is `done`. Otherwise read the sources the pipeline names, or, when it names none, every source of the interactive steps' step 1 this run can reach without asking anyone: repository documents, other coding agents' rule files, git history and a scan of the code; outside sources only through tools the pipeline provides. A run without a member has no local memory to read.

## 2. Cut each source into proposals

Cut as the interactive steps' step 2 does: one thing per proposal, a title, a one-line summary, a type, a body of at most 600 words in the source's own wording, a proposed level, the source in its form (`repository:path`, `commit:repository@revision`, `wiki:<page>`, `ticket:<reference>`, `pr-comment:<reference>`) and the writer from `git blame` or the source. Leave out the same things, from every source, and keep each with its reason: what the environment already states, claims that no longer hold against the code, one member's preferences, and secrets (note where a secret is kept instead). Collapse an identical rule found in several places into one proposal listing every source.

## 3. Write the proposals file

Write one proposals file for the repository, `shared-memory-proposals-<repository>.json`, where the pipeline keeps its artifacts. It is JSON, one entry per proposal:

```json
{
  "repository": "<repository>",
  "project": "<project ID>",
  "written_at": "<ISO 8601 time>",
  "proposals": [
    {
      "title": "...",
      "summary": "...",
      "type": "convention",
      "body": "...",
      "level": "project",
      "source": "<repository>:CLAUDE.md",
      "writer": "@<GitHub username, or null when there is no single writer>"
    }
  ],
  "left_out": [
    { "source": "<repository>:README.md", "passage": "<a few words of it>", "reason": "..." }
  ]
}
```

**Done when** every source read is accounted for passage by passage: each passage is in a proposal or in `left_out` with its reason.

## 4. Record progress

Call `record_onboarding_progress` with `repository="<repository>"`, `status="partly_done"` and `left_out` set to the number of passages left out. The repository stays partly done until a member loads the file, approves and promotes.
