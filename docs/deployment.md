# Deploying Shared Memory

For the person running the server. This covers running it for the team on one Linux host over HTTPS, the nightly backup, and restoring from that backup. Words in **bold** are defined in [`CONTEXT.md`](../CONTEXT.md). To try the server on your own machine instead, see [`setup.md`](./setup.md).

Everything lives in [`deploy/`](../deploy): a Compose file that runs the server behind Caddy (automatic HTTPS), Postgres with pgvector, and a backup container.

## What you need

- A Linux host with Docker and Docker Compose v2, **2 vCPU and 4GB of memory**, and about 25GB of disk.
  The build compiles the console with Vite and installs onnxruntime for the server; below roughly 2GB the
  console build is killed by the kernel and the error does not say so. 2GB works with 2GB of swap added.
- A domain name (for example `memory.example.com`) whose DNS record points at the host, with ports 80 and 443 open. Caddy uses both to get and renew the certificate. **On a cloud host, open them in the provider's firewall as well as the host's** — a VM's own rules are not the only ones in the way, and a blocked port 80 shows up only as a certificate that never arrives.
- A **private** git repository for backups, for example `your-org/shared-memory-backup` on GitHub, and an SSH key with write access to it.
- For the **console**, a GitHub OAuth app (free, made in a few clicks below). Without one the console still runs, but nobody can sign in to it.

## Deploy

1. Clone this repository on the host and go to `deploy/`.
2. Create the backup key and give it write access to the backup repository. On GitHub, add the public key under the backup repository's **Settings → Deploy keys**, with **Allow write access** ticked:

   ```bash
   ssh-keygen -t ed25519 -N "" -C shared-memory-backup -f backup_key
   ```

3. Copy `.env.example` to `.env` and fill it in:

   | Setting | Meaning |
   |---|---|
   | `SHARED_MEMORY_DOMAIN` | The server's domain name |
   | `POSTGRES_PASSWORD` | A long random password; Postgres is never exposed outside the stack |
   | `BACKUP_REMOTE` | The backup repository, for example `git@github.com:your-org/shared-memory-backup.git` |
   | `BACKUP_SSH_KEY` | The private key from step 2 (default `./backup_key`) |
   | `BACKUP_TIME`, `TZ` | When the nightly backup runs (default 02:00 UTC) |

4. Check the host is ready. This takes a couple of seconds and refuses to let you spend several minutes
   building on a host that cannot finish:

   ```bash
   ./preflight.sh
   ```

5. Start everything:

   ```bash
   docker compose up -d --build
   ```

6. Create the team and its **owner**. The owner's **personal token** is printed once; hand it to the owner privately. `--owner-github` is the owner's GitHub username, which lets them sign in to the console:

   ```bash
   docker compose exec server shared-memory setup --team acme --owner-member-id E1001 --owner-name "Olive Owner" --owner-github olive
   ```

7. Check HTTPS works. This should print `200`:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -X POST https://memory.example.com/hooks/session-start -d '{}'
   ```

8. Run the first backup now, to check the key can push:

   ```bash
   docker compose exec backup backup now
   ```

Members use `https://memory.example.com` as the **Shared Memory server URL** in the plugin ([`setup.md`](./setup.md) §4), and open the **console** at `https://memory.example.com`.

To update the server later, pull this repository and run `docker compose up -d --build` again.

## The console

The console is served at the domain by the same Caddy that fronts the server, so it needs no hosting of its own. Signing in to it uses GitHub ([ADR-0007](./adr/0007-the-console-signs-in-with-github.md)).

1. Register a GitHub OAuth app at **Settings → Developer settings → OAuth Apps → New OAuth App** (on your account or your organisation):

   | Field | Value |
   |---|---|
   | Application name | Shared Memory |
   | Homepage URL | `https://memory.example.com` |
   | Authorization callback URL | `https://memory.example.com/api/sign-in/github/callback` |

2. Put the app's client ID and a generated client secret in `.env` as `SHARED_MEMORY_GITHUB_CLIENT_ID` and `SHARED_MEMORY_GITHUB_CLIENT_SECRET`, then `docker compose up -d`.
3. Link each member's GitHub account, so they can sign in. The owner's was linked by `setup --owner-github`:

   ```bash
   docker compose exec server shared-memory link-github --team acme --member-id E1042 --github dana
   ```

A member who signs in sees who they are; what else the console does arrives with the rest of issue #22. Until the GitHub app is configured, the console opens and says that signing in isn't set up on this server.

## Backups

Every night at `BACKUP_TIME`, the backup container pushes two branches to the backup repository:

- **`main`**: the memory folder's git history, so every memory and every earlier version of it.
- **`database`**: a dump of Postgres, one commit per night. It holds members, personal tokens (hashed), projects, repositories, pins, challenges and notices. It leaves out the search index, which is rebuilt from the memory files.

The database is dumped before the memory history is pushed, so the backup never refers to a memory it doesn't contain. A failed server loses at most the changes since the last backup.

**Checking on it:**

- `docker compose logs backup` shows each backup starting and finishing, or `Backup FAILED` with the reason.
- `docker compose ps` shows the backup container as `unhealthy` when no backup has succeeded for more than 26 hours.

## Restore

Use this on a fresh host, or on the same host after its volumes are lost. The restore refuses to run over a memory folder or database that already holds memory.

1. If the old server is still reachable, stop it, so members don't keep writing to it.
2. On the new host, follow **Deploy** steps 1–3 with the same `BACKUP_REMOTE` and a key that can read it. Point the domain's DNS record at the new host.
3. Restore, then start everything and rebuild the search index. The first reindex downloads the search model (about 70 MB):

   ```bash
   docker compose up -d db
   docker compose run --rm backup restore
   docker compose up -d --build
   docker compose exec server shared-memory reindex
   ```

Everything in the last backup comes back: memories with their history, members and their personal tokens (members don't need new ones), projects, pins and open challenges. The next nightly backup continues the backup repository's history.

**Practice a restore** now and then, without touching the running server, by restoring into a throwaway stack with its own project name, for example `docker compose -p restore-drill ...`. Remove it afterwards with `docker compose -p restore-drill down -v`. Its Caddy needs other host ports than 80 and 443 while the real server runs.
