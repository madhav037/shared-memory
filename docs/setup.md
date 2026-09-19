# Setting up Shared Memory

This guide covers the three people involved: the person running the server, the owner, and every member. Words in **bold** are defined in [`CONTEXT.md`](../CONTEXT.md).

## 1. Run the server (the person running the server)

To run it for your team on a server, with HTTPS and nightly backups, follow [`deployment.md`](./deployment.md). The steps below run it on your own machine to try it out.

Requirements: Docker with Compose.

```bash
docker compose up -d db server
```

This starts Postgres (with pgvector) on port 5433 and the server on port 8000. The memory folder and the search model live in the `memory-data` volume.

Server settings, as environment variables on the `server` service:

| Variable | Meaning | Default |
|---|---|---|
| `SHARED_MEMORY_DATABASE_URL` | Postgres connection | set in `compose.yaml` |
| `SHARED_MEMORY_ROOT` | Memory folder (a git repository) | `/data/memory` |
| `SHARED_MEMORY_MODEL_CACHE` | Where the local embedding model is stored | `/data/models` |
| `SHARED_MEMORY_ALLOWED_HOSTS` | Host names the server answers to, comma separated (for example `memory.example.com`). Leave empty for localhost only. | empty |
| `SHARED_MEMORY_PLUGIN_MARKETPLACE` | GitHub `owner/repo` that hosts the plugin marketplace | `madhav037/shared-memory` |

The first search downloads the embedding model (about 70 MB) into the model cache.

### Create the team and its owner

```bash
docker compose exec server shared-memory setup --team acme --owner-employee-id E1001 --owner-name "Olive Owner"
```

The command prints the **owner**'s **personal token** once. Hand it to the owner privately.

### Rebuild the search index

If the search index is ever lost or damaged, rebuild it from the memory files:

```bash
docker compose exec server shared-memory reindex
```

## 2. Add members (the owner)

In the console's **Members**, or from your own coding agent once it is connected (section 4), ask it to:

- **add a member**: `add_member` with their employee ID and name. Their personal token is shown once; pass it to them privately.
- **remove a member**: `remove_member`. Their token stops working; their memories stay, credited to them.
- **reissue a token**: `reissue_token`, when a token has leaked.

## 3. Connect a repository (any member, once per repository)

Create a project for the repository: **New project** on the console's front page, or ask a coding agent that is already connected to call `create_project`. For another repository of the same product, reuse the existing project instead. Either way you get the files that connect the repository to its project, for every **coding agent** the team uses. The console shows them in the project's **Settings**, and one agent at a time on **Connect your agent**.

| Coding agent | File the repository commits |
|---|---|
| Claude Code | `.claude/settings.json` |
| Codex | `.codex/config.toml` |
| GitHub Copilot | `.vscode/mcp.json` for VS Code, `.github/mcp.json` for Copilot CLI |
| Gemini CLI | `.gemini/settings.json` |
| Cursor | `.cursor/mcp.json` |
| Devin Desktop | `.devin/mcp_config.json` |
| Every agent | a Shared Memory section in `AGENTS.md`, and the skill in `.agents/skills/shared-memory/SKILL.md` |

Commit the files for the agents your team uses, merging each into any file already there. They name the project and the repository, never a personal token. Cline keeps its MCP servers on each machine rather than in the repository, so each member who uses Cline adds the project's entry once (section 4).

For Claude Code, the settings look like this:

```json
{
  "extraKnownMarketplaces": {
    "shared-memory": { "source": { "source": "github", "repo": "madhav037/shared-memory" } }
  },
  "enabledPlugins": { "shared-memory@shared-memory": true },
  "env": {
    "SHARED_MEMORY_PROJECT": "billing-3f9a2c",
    "SHARED_MEMORY_REPOSITORY": "billing-web"
  }
}
```

Several repositories can use the same project ID, each with its own repository name.

Whoever creates a project becomes its first **project lead**: they appoint other leads and look after its repositories. The project's **Settings** in the console show each repository with the files to commit into it. A project lead can also read the audit log for their own projects.

A project is open to the whole team unless a lead or an admin **restricts** it. A restricted project can be reached only by the members on its **access list**, its leads and the team's admins: everyone else stops seeing it listed, its memory tools refuse, and a session started in one of its repositories is told why and gets no briefing or recall. Team memory stays readable by the whole team. Opening a project up again keeps its access list, so restricting it later lets the same members straight back in.

## 4. Join as a new member

Your personal token comes from whoever added you. You can also issue yourself a new one on the console's **Connect your agent** page, which shows the steps below for each agent.

### Claude Code

1. Clone the repository and open it in Claude Code.
2. Trust the repository's settings when Claude Code asks. That adds the marketplace and enables the **shared-memory** plugin; there is no separate install prompt.
3. When the plugin is enabled, it asks for:
   - **Shared Memory server URL**, for example `https://memory.example.com`
   - **Your personal token** (stored as a sensitive value, and masked on screen)
4. Start a session. The **briefing** appears at session start, and **recall** is added to prompts.

Access to the plugin marketplace repository is needed to install the plugin. While the repository is private, members need read access to it on GitHub.

The plugin's hooks call the server with `curl`, which ships with Windows 10 and later, macOS and Linux. On Windows, Claude Code runs the hooks with Git Bash (from Git for Windows).

### Every other coding agent

1. Set your personal token once on your machine, in the `SHARED_MEMORY_TOKEN` environment variable (on Windows, `setx SHARED_MEMORY_TOKEN <token>`), then restart the agent. VS Code asks for the token the first time instead, and keeps it.
2. Open the repository. Trust the folder or approve the server when the agent asks; most agents ignore a repository's own settings until you do.
3. **Cline**: add the project's entry from **Connect your agent** to Cline's MCP settings, once for each project.
4. **Devin Desktop**: its documentation doesn't yet say it reads environment variables in headers. If it connects without your token, put the same entry, with your own token, in `.devin/mcp_config.local.json`, which git never commits.

These agents don't get the briefing and recall by themselves yet. The server's instructions and the `AGENTS.md` section ask them to call `briefing` at the start of a task and `search` before answering, and each change they make is recorded with the agent it came from.

## 5. Decide what every session is briefed with

Open a project in the console and a memory shows whether it is **pinned**. Pinning a project or team memory — or a topic folder, which pins its index — puts it into the briefing every session in that project receives. The project page lists everything pinned in it with roughly how many tokens each one costs; when a pin would take the briefing over its cap, the console says so and shows what is already pinned, so you can choose what to unpin. The same thing can be done from a session with the `pin` and `unpin` tools.

## 6. Decide what the team no longer believes

The console opens on the **challenges** waiting for your decision, with both memories side by side: what the memory says now, and what is offered in its place. Accepting one supersedes the memory; rejecting leaves it as it is and the challenger's memory stays personal memory. Several challenges against one memory are shown together, and accepting one closes the others, telling whoever raised them why. Until the fallback period passes the author decides; after it, or once the author has left the team, any member can.

A memory that is no longer true and has nothing to replace it is **retired** from its own page. Retiring your own memory takes effect at once; retiring another member's raises a challenge for that author to decide. The **Challenges** page also shows every challenge you raised and how each one ended.

## 7. Repositories without a project

A repository whose files don't name a project behaves exactly as before: hooks add nothing, and memory tools reply that the repository isn't connected to a project and how to connect it.
