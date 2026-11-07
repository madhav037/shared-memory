# Listing Shared Memory

A checklist for the developer. Nothing here is submitted for you: every step below needs your own GitHub login or an account on the directory. Words in **bold** are defined in [`CONTEXT.md`](../CONTEXT.md).

Every listing points at the GitHub repository, <https://github.com/madhav037/shared-memory>, and its docs ([`setup.md`](./setup.md), [`deployment.md`](./deployment.md)). There is no product website to link. The code is source-available under FSL-1.1-ALv2. Say so in any form that asks for a license, and in no listing call it by any other name.

## Before you submit anything

- [ ] The GitHub repository is public, with the README and `LICENSE` on the default branch.
- [ ] `server.json` at the root has the version you are releasing (`version`), and it matches a tagged release.
- [ ] `plugin/.claude-plugin/plugin.json` has the same release's version.
- [ ] `uv run pytest tests/test_listing.py -q` passes. It checks `server.json` against the registry's JSON schema (vendored at `tests/schemas/mcp-registry-server.schema.json`, the 2025-12-11 version `server.json` names in `$schema`) and that both plugin manifests parse.

Shared Memory is a **remote** MCP server: each team runs its own server and members connect over streamable HTTP at `https://<their server>/mcp`, with their **personal token** as a bearer token. `server.json` therefore lists a `remotes` entry with the server host name as a variable, and no `packages` entry: there is no published package or image to point at.

## The official MCP Registry

Follows the registry's [publishing guide](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx) for a remote-only server.

1. Install `mcp-publisher` (`brew install mcp-publisher`, or a binary from the registry's GitHub releases).
2. From the root of this repository: `mcp-publisher login github`, and approve the device code on GitHub. The name `io.github.madhav037/shared-memory` only works when you log in as `madhav037`.
3. `mcp-publisher publish`.
4. Check it: `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.madhav037/shared-memory"`.

A new release means a new `version` in `server.json` and another `mcp-publisher publish`.

## The Claude Code plugin marketplace

The repository is itself a marketplace (`.claude-plugin/marketplace.json`) with one plugin (`plugin/`). Nothing to submit for that: members add it with `/plugin marketplace add madhav037/shared-memory` and `/plugin install shared-memory@shared-memory`, or through the settings a project's **Settings** page gives them.

Before a release, run `claude plugin validate .` from the repository root. To be listed in Anthropic's own directory as well, follow the current *Publish and distribute a plugin* page in the Claude Code docs, and its pre-submission checklist.

## Directories

For each, sign in, add the GitHub repository, and paste the descriptions below. These directories change their forms often; follow the page each one shows you rather than this list.

- [ ] **Smithery**: add the server as a remote (streamable HTTP) server. Because every team has its own address, say that members enter their own.
- [ ] **Glama**: claim or add the GitHub repository.
- [ ] **mcp.so**: submit the GitHub repository.
- [ ] **Cursor's MCP directory**: submit through the page Cursor documents for its directory.
- [ ] **VS Code's MCP gallery**: it reads from the official MCP Registry, so listing there first is the step; check the gallery after the registry publish.
- [ ] **Docker MCP Catalog**: it lists container images and none is published, so skip it until the server's image is.

## Descriptions to paste

**Short** (at most 100 characters, the registry's limit):

> A memory server every member's coding agent reads and writes, with a console to govern it.

**Long**:

> Shared Memory is a memory server that every member's coding agent reads and writes, so what one member's agent learns reaches every other member's agent and the team's ways of working stay consistent. Memory is plain Markdown files in a git history, with levels of weight: project memory over team memory over personal memory. A console lets members read memory like documentation, pin it, decide challenges and retire it; writing and promoting stay in the coding agent, where contradictions are checked. Each team runs its own server (Docker Compose, HTTPS and nightly backups included). Works with Claude Code through a plugin, and with Codex, GitHub Copilot, Gemini CLI, Cursor, Devin Desktop and Cline over MCP. Source-available under FSL-1.1-ALv2.

**Tags**: memory, team, coding agents, MCP, knowledge sharing.
