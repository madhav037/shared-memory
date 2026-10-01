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

## Sizing

The server runs several worker processes, so saves and reads in different areas use more than one CPU (ADR-0013). Two
settings in `.env` (both optional) size them:

| Setting | Default | Meaning |
|---|---|---|
| `SHARED_MEMORY_WORKERS` | 2 | Server processes. `shared-memory serve` prepares the database and the memory folder once, then starts this many workers. |
| `SHARED_MEMORY_DATABASE_CONNECTIONS` | 40 | Postgres connections all workers may hold together. Each worker's pool is its share (never fewer than 4), and saves may hold half of it. |

- **Two workers fit an e2-small (2 vCPU, 2GB).** Each worker loads the embedding model, about 350MB, so memory grows
  with the worker count: on 2GB, stay at 2 workers, and add swap if you also build on the host.
- **Keep the connections under Postgres's `max_connections`** (100 by default) **minus what the backup and your own
  tools take.** The default 40 leaves plenty of room.
- One worker (`SHARED_MEMORY_WORKERS=1`) runs the server in a single process, as before.

## The query cache's counts

Every recall and search turns its query into an embedding by running the model. Each worker keeps the embeddings of
its last 1,024 queries, so a query repeated word for word on the same worker skips the model. Each worker counts how
often that happens and writes the counts to its log, which `docker compose logs server | grep "Query cache"` shows:

```
INFO:     Query cache worker=17 minutes=15 | period: recall hits=3 misses=41, search hits=6 misses=9, console-search hits=0 misses=2 | since start: recall hits=40 misses=512, search hits=71 misses=120, console-search hits=4 misses=19
```

- **`worker`** is the worker's process ID. Each worker has its own cache and writes its own lines; add the lines of
  every worker together for the whole server.
- **A hit** is a query the cache answered; **a miss** is one the model had to run for. The share of hits,
  hits ÷ (hits + misses), is how much the cache saves.
- The counts are split by where the query came from: **`recall`** (recall on a prompt), **`search`** (a session's
  `search` tool) and **`console-search`** (search in the console).
- **`period`** counts the queries since the worker's last line (or since it started), and **`minutes`** is how long
  that was. **`since start`** counts everything since the worker started. A restart sets every count to zero, as it
  empties the cache.
- A worker writes its line on the first query that arrives once `SHARED_MEMORY_QUERY_CACHE_LOG_MINUTES` (default 15,
  optional in `.env`) have passed since its last one. A worker nobody queries writes nothing, so after a quiet
  stretch `minutes` is longer than the setting.

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

## Behind a CDN

The server can sit behind a CDN such as Cloudflare or CloudFront, for DDoS protection and to keep the host's address private. It is suited to it: the MCP endpoint answers plain JSON with no session to keep, hooks and console requests are short, and nothing reads the client's IP. Five things need setting on the CDN.

1. **Forward the real `Host` header.** The server accepts only requests addressed to `SHARED_MEMORY_DOMAIN` (it is the server's `allowed_hosts`), and Caddy picks its site by the same name. A CDN that rewrites `Host` to its own origin name gets every MCP call refused. Cloudflare forwards it as it is; on CloudFront, use an origin request policy that forwards the viewer's `Host`.
2. **Encrypt all the way to Caddy, and check its certificate.** On Cloudflare that is **SSL/TLS → Full (strict)**; Flexible sends personal tokens to the host unencrypted. With the CDN in front, Caddy's usual way of proving it owns the domain can fail, so give it a certificate another way:
   - a **DNS challenge**: build Caddy with your DNS provider's module (for example `caddy-dns/cloudflare`) and add `tls { dns cloudflare {env.CF_API_TOKEN} }` to the site in `deploy/Caddyfile`; or
   - an **origin certificate** from the CDN (Cloudflare's Origin CA, valid only between Cloudflare and the host): mount it into the Caddy container and use `tls /certs/origin.pem /certs/origin.key`.
3. **Refuse bodies over 1 MB at the CDN too.** Caddy refuses anything bigger (`request_body` in `deploy/Caddyfile`), and no request the server needs comes near it. Matching the limit at the edge stops the oversized ones before they reach the host: on Cloudflare, a WAF custom rule blocking `http.request.body.size gt 1048576`; on CloudFront, an AWS WAF size constraint.
4. **Never cache `/api/*`, `/mcp*` or `/hooks/*`.** Every answer on those paths is one member's: their memory, their briefing, their console. The server marks each of them `Cache-Control: no-store`, but set the CDN to bypass its cache for them as well, so a rule set elsewhere can't override it: a Cloudflare cache rule set to **Bypass cache**, or CloudFront behaviours for those paths using the `CachingDisabled` policy with every method allowed. Everything else is the console's own files, which can be cached.
5. **Wait longer for the origin than the slowest save can take.** Saves take their turn one at a time, so a busy team's save can wait for tens of seconds before it answers; under heavy load in testing, a queued save took around 25 seconds. Keep the CDN's origin timeout well above that, at 60 seconds or more. Cloudflare's default of 100 seconds is enough; CloudFront's default of 30 is not, so raise its origin response timeout.

Then run step 7 of [Deploy](#deploy) against the domain again: it now goes through the CDN.

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
