# Shared Memory

A memory server that every member's coding agent reads and writes, plus a console for governing it. What one member's
agent learns reaches every other member's agent, so the team's ways of working stay consistent.

Memory is plain Markdown files with a small header, on a server, with every change in a git history. The console shows
exactly what every coding agent reads, word for word. It governs memory (pin, unpin, decide challenges, retire) but never
writes it: writing, editing and promoting happen in a member's own coding agent, where the check for contradictions runs.

## Levels

Every memory has a level, and the levels have a fixed order of weight:

```
project memory   holds for everyone working on one project        heaviest
team memory      holds for every project in the team
personal memory  one member's note, readable by all, not accepted by the team   lightest
```

Local memory, a coding agent's own built-in memory on one member's machine, reaches the team only when that member
imports it. A personal memory becomes team or project memory by being promoted, and a challenge decides a dispute about
a memory that is already accepted. Terms are defined in [`CONTEXT.md`](CONTEXT.md).

## Self-host it in 5 steps

You need a Linux host with Docker and Docker Compose v2 (2 vCPU and 4GB of memory), a domain name pointing at it, and a
private git repository for backups. The full guide is [`docs/deployment.md`](docs/deployment.md).

1. Clone this repository on the host and go to `deploy/`.
2. Make a backup key and give it write access to your private backup repository.
3. Copy `.env.example` to `.env` and fill in the domain, a database password and the backup settings.
4. Run `./preflight.sh`, then `docker compose up -d --build`. Caddy gets the HTTPS certificate.
5. Create the team and its owner. The owner's personal token is printed once.

```bash
docker compose exec server shared-memory setup --team acme --owner-member-id E1001 --owner-name "Olive Owner" --owner-github olive
```

To try it on your own machine first, `docker compose up -d db server` runs it on port 8000
([`docs/setup.md`](docs/setup.md), section 1).

## Connect your coding agent

The owner adds each member, who gets a personal token shown once. Create a project for each repository: the console
then shows the files to commit, for every agent your team uses. [`docs/setup.md`](docs/setup.md) has the details.

**Claude Code** uses the plugin. The repository's `.claude/settings.json` adds this repository as a marketplace and
enables the plugin, so a member trusts the settings and is asked for the server URL and their personal token. Or add it
by hand:

```
/plugin marketplace add madhav037/shared-memory
/plugin install shared-memory@shared-memory
```

**Every other coding agent** connects to the server over MCP, as a streamable HTTP server at `https://<your server>/mcp`
with the personal token as a bearer token in the `Authorization` header: Codex, GitHub Copilot, Gemini CLI, Cursor,
Devin Desktop and Cline. Set the token once in the `SHARED_MEMORY_TOKEN` environment variable. The files a project commits
name the project and the repository in two more headers, `X-Shared-Memory-Project` and `X-Shared-Memory-Repository`.

## Tools the server offers

| Group | Tools |
|---|---|
| Start a session | `briefing`, `set_activity`, `guide`, `onboard` |
| Find memory | `search`, `tree`, `list`, `read` |
| Write memory | `remember`, `edit_memory`, `delete_memory`, `promote`, `save_known_issue` |
| Govern memory | `pin`, `unpin`, `retire`, `decide_challenge`, `add_to_foundation` |
| Avoid collisions | `take_lock`, `release_lock`, `never_lock` |
| Plan work | `board`, `add_card`, `update_card`, `claim_card`, `comment_card`, `delete_card` |
| Run the team | `create_project`, `add_foundation`, `add_member`, `remove_member`, `reissue_token` |

## Security

- A **rate limit** counts calls per personal token, and per address for calls without one. A call over the limit is
  refused with the seconds to wait; a limited hook adds nothing and never blocks the coding agent.
- A memory's text reaches a prompt inside a **fence** its own text cannot forge, so a memory cannot pass itself off as an
  instruction from the server.
- A personal token is shown once, when issued. A restricted project is invisible to anyone outside its access list.
- Nothing is sent home. A self-hosted server reports errors only if you set `SHARED_MEMORY_SENTRY_DSN`, and then with
  private data removed.
- The threat model is in [`docs/threat-model.md`](docs/threat-model.md).

## License

Shared Memory is source-available under the Functional Source License, FSL-1.1-ALv2 (see `LICENSE`).
You may read, run and modify it for any purpose except a competing use. Each release becomes Apache 2.0
two years after its release. Self-hosting needs a paid license for teams.
