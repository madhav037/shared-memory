# Deploying Shared Memory

For the person running the server. This covers running it for the team on one Linux host over HTTPS, the nightly backup, and restoring from that backup. Words in **bold** are defined in [`CONTEXT.md`](../CONTEXT.md). To try the server on your own machine instead, see [`setup.md`](./setup.md).

Everything lives in [`deploy/`](../deploy): a Compose file that runs the server behind Caddy (automatic HTTPS), Postgres with pgvector, and a backup container.

## What you need

- A Linux host with Docker and Docker Compose.
- A domain name (for example `memory.example.com`) whose DNS record points at the host, with ports 80 and 443 open. Caddy uses both to get and renew the certificate.
- A **private** git repository for backups, for example `your-org/shared-memory-backup` on GitHub, and an SSH key with write access to it.

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

4. Start everything:

   ```bash
   docker compose up -d --build
   ```

5. Create the team and its **owner**. The owner's **personal token** is printed once; hand it to the owner privately:

   ```bash
   docker compose exec server shared-memory setup --team acme --owner-employee-id E1001 --owner-name "Olive Owner"
   ```

6. Check HTTPS works. This should print `200`:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -X POST https://memory.example.com/hooks/session-start -d '{}'
   ```

7. Run the first backup now, to check the key can push:

   ```bash
   docker compose exec backup backup now
   ```

Members use `https://memory.example.com` as the **Shared Memory server URL** in the plugin ([`setup.md`](./setup.md) §4).

To update the server later, pull this repository and run `docker compose up -d --build` again.

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
