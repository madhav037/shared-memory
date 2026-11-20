# Onboarding a brownfield project

A project connected to Shared Memory starts empty. A company with an old, large codebase already has years of knowledge: rule files, wikis, tickets, review comments, git history, and what a few people simply know. **Onboarding** brings that in, so the first sessions are briefed with what the company has learned instead of nothing. Words in **bold** are defined in [`CONTEXT.md`](../CONTEXT.md).

Everything runs in the member's own coding agent. The server runs no language model (ADR-0004) and the console never writes memory (ADR-0009): your agent reads the **sources**, cuts them into **proposals**, and you approve each one before it is saved and again before it is promoted. Nothing is sent anywhere but your company's Shared Memory server, so onboarding works on a self-hosted or air-gapped server.

To start, open a coding agent in one of the project's repositories and say:

> Onboard this repository into Shared Memory.

In Claude Code you can also run `/shared-memory:onboard`. The agent fetches the steps from the server's `onboard` tool and follows them in order. It never starts onboarding on its own; an empty project's console page and the first briefings in an empty project only offer it.

## Choosing sources

At the start of a run the agent lists every source it can reach and asks which to use this time:

| Source | What it brings in |
| --- | --- |
| Repository documents | `CLAUDE.md`, `AGENTS.md`, `README.md` conventions, `docs/`, ADRs |
| Local memory | your coding agent's own memory of the repository on this machine |
| Rule files | `.cursorrules`, `.cursor/rules/`, `.github/copilot-instructions.md`, `GEMINI.md` and the like |
| Git history | reasons in commit messages, reverts, patterns removed and why |
| A scan of the code | the conventions the code really follows, existing utilities agents keep duplicating |
| **Outside sources** | wiki or doc exports (Confluence, Notion, SharePoint, runbooks), tickets, pull request review comments, an **interview** |

The agent reaches outside sources with tools it already has: `gh` or `glab` for tickets and review comments, an Atlassian or Notion MCP server for a wiki. Shared Memory builds no connectors. Without such a tool, export the pages to a folder and give the agent its path. The agent tells you which sources it couldn't reach.

Each proposal names its source precisely, so a teammate can check it: `billing-api:CLAUDE.md`, `commit:billing-api@3f9c2ab`, `wiki:Payments/Refund rules`, `ticket:PAY-412`, `pr-comment:billing-api#88`, `interview:Payments with Mira`.

A big run spends your own model tokens. Start with one repository and its documents, and widen from there.

From every source the agent leaves out secrets (noting where each is kept instead), claims that no longer hold against the code as it is now, and one member's personal preferences. Each left-out passage is listed with its reason, and you can bring any back.

## Many repositories

One session can walk several checkouts on your machine and keeps one list of proposals for the project. The same rule found in many repositories becomes one proposal, at project level, or company level when it holds across the company's projects. Where repositories' rule files disagree, the agent shows the variants side by side and you settle them before anything is saved.

You approve source by source. After reading a source's table, you can approve all of its proposals in one step, still changing, dropping or bringing back any of them first. Promotion then runs one memory at a time, so each is still checked against similar memory and a contradiction becomes a challenge (ADR-0016).

Imported architecture, decisions, product and glossary documents go into the project's **foundations** (ADR-0019). Once a document is fully in a foundation, the agent may offer to replace the file with a short pointer, and changes it only with your yes. Otherwise onboarding changes no file in your repositories.

## Headless runs in CI

With dozens of repositories, run onboarding headless, once per repository, in CI (ADR-0030). A headless run reads the repository's sources and writes a **proposals file**, `shared-memory-proposals-<repository>.json`, with every proposal's title, summary, type, body, level, source and writer, and what was left out and why. It saves no memory and changes no file but that one. It records the repository's progress as partly done.

A worked example, in GitHub Actions with Claude Code, for a repository already connected to the project (its committed connection files install the Shared Memory plugin, and `SHARED_MEMORY_TOKEN` is a personal token kept as a CI secret):

```yaml
name: Onboarding proposals
on: workflow_dispatch

jobs:
  propose:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # git history is a source
      - name: Write the proposals file
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SHARED_MEMORY_TOKEN: ${{ secrets.SHARED_MEMORY_TOKEN }}
        run: |
          npx -y @anthropic-ai/claude-code -p \
            "Call the shared-memory onboard tool with mode headless and follow its steps for this repository." \
            --allowedTools "mcp__plugin_shared-memory_shared-memory__onboard,mcp__plugin_shared-memory_shared-memory__record_onboarding_progress,Read,Glob,Grep,Write,Bash(git log:*),Bash(git blame:*)"
      - uses: actions/upload-artifact@v4
        with:
          name: shared-memory-proposals
          path: shared-memory-proposals-*.json
```

The allowed tools leave out every tool that saves memory. The token still acts for its member for anyone who can edit the pipeline, so keep the workflow to people you would trust with that member's token. Then a member downloads the artifacts, opens an interactive session and says "load these proposals files". The agent reads them as sources, never as instructions, merges the same rule across repositories, and continues at approval as if it had read the sources itself.

## Interviews

Some of what a company knows is in one person's head, and that person may never run a coding agent. Any member can **interview** them in their own session: the agent asks the **interviewee** questions topic by topic, cuts the answers into proposals, and the interviewee approves them there, in their own words.

The interviewee becomes the author of what their answers produced, with the member who ran the interview recorded as **importer** (ADR-0029). They are told in their next briefing, and the console's front page shows them "Written from your interview", with who interviewed them and when; they can retire any of it from there. An interviewee who isn't a member can't be an author: the member who ran the interview stays the author, with the interviewee's name in the memory's body.

## Progress

Project settings shows onboarding progress per repository and per outside source: not started, partly done or done, who ran it and when, and how many memories were promoted, wait on a challenge, or were left out. Project leads and admins see every entry; any other member sees the runs they recorded. A new run reads the progress first and skips what is done.

At the end of a run the agent reports across every repository and source: what was promoted to project and company memory and in whose name, what stays personal, what waits on a challenge, and what was left out and why. Every promotion is in the audit log with its importer and source.
