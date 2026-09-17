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

In a Claude Code session with the plugin installed, ask Claude to:

- **add a member**: `add_member` with their employee ID and name. Their personal token is shown once; pass it to them privately.
- **remove a member**: `remove_member`. Their token stops working; their memories stay, credited to them.
- **reissue a token**: `reissue_token`, when a token has leaked.

## 3. Connect a repository (any member, once per repository)

In a Claude Code session inside the repository, ask Claude to create a project (or reuse an existing project ID for another repository of the same product). `create_project` returns settings to merge into the repository's committed `.claude/settings.json`:

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

Commit the file. Several repositories can use the same project ID, each with its own repository name.

## 4. Join as a new member

1. Clone the repository and open it in Claude Code.
2. Trust the repository's settings when Claude Code asks. That adds the marketplace and enables the **shared-memory** plugin; there is no separate install prompt.
3. When the plugin is enabled, it asks for:
   - **Shared Memory server URL**, for example `https://memory.example.com`
   - **Your personal token** (stored as a sensitive value, and masked on screen)
4. Start a session. The **briefing** appears at session start, and **recall** is added to prompts.

Access to the plugin marketplace repository is needed to install the plugin. While the repository is private, members need read access to it on GitHub.

The plugin's hooks call the server with `curl`, which ships with Windows 10 and later, macOS and Linux. On Windows, Claude Code runs the hooks with Git Bash (from Git for Windows).

## 5. Repositories without a project

A repository whose settings don't name a project behaves exactly as before: hooks add nothing, and memory tools reply that the repository isn't connected to a project.
