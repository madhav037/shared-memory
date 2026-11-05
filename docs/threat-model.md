# Threat model

A one-page STRIDE pass over Shared Memory's three entry points, built from the trust-boundaries view of
[`architecture.html`](architecture.html#trust) (crossings B1 to B9). Each threat names the check that stops it, with
the code that does it, or the issue that tracks the missing check. Written 2026-11-05 for #377 (part of #375).

**Assumed:** a member is trusted to read all of their team's memory except restricted projects they aren't on; TLS ends
at Caddy; the server publishes no port in production (`deploy/compose.yaml`), so only Caddy reaches it. Paths below are
relative to the repository root; `src/shared_memory/` is shortened to `sm/`.

| Entry point | Crossings | Credential |
| --- | --- | --- |
| MCP over HTTP: `/mcp` and the hooks' `/hooks/*` | B1, B2, B4, B6, B7 | Personal token (`Authorization: Bearer`), plus project and repository headers, which are not secrets (ADR-0005) |
| Console JSON API: `/api/*` | B3, B4, B5 | Console session cookie from a GitHub sign-in |
| Deploy path: GitHub Actions to the host | B8, B9 | SSH deploy key in the `production` environment; a separate read-only backup key |

## 1. MCP over HTTP: `/mcp`, `/hooks`

| | Threat | Check | Where |
| --- | --- | --- | --- |
| **S** | Calling as another member, or with a revoked token | Every call authenticates again: the token's SHA-256 is looked up; an unknown or revoked token, or a removed member, is refused. Tokens are 256-bit. | `sm/identity.py:160-196`, `:90`, `:153`; `sm/app.py:303-312` |
| **T** | Writing outside the team's folder, or into a restricted project | Paths refuse `..`, absolute paths and links; any path argument is checked against the projects the member can't reach. | `sm/store.py:302`; `sm/identity.py:61` |
| **T** | Changing another author's memory | Only through a challenge, decided by the author, a lead or keeper, or an admin. | `sm/challenges.py:291` |
| **R** | A member denies a change | Every memory change goes to the audit log with member, project, path and coding agent; each commit carries the member as its author. | `sm/audit.py:170`; `sm/store.py:163` |
| **I** | Reading a restricted project, or another team | The project header must be a project in the member's team, and a restricted one needs the access list. | `sm/identity.py:476`, `:501` |
| **I** | Secrets leaking through memory, or token theft from the database | Text that looks like a secret is refused on save; Postgres holds only token hashes. | `sm/validation.py:60`; `sm/identity.py:90` |
| **I** | Listing tools without a token | Accepted: listing is presentation only, the schemas are public in the repository, and calling a tool needs a token. | `sm/listing.py` |
| **D** | Huge bodies | Caddy refuses bodies over 1 MB; a hook authenticates before reading its body, then reads at most the limit. | `deploy/Caddyfile:15-17`; `sm/app.py:388`, `:184`, `:400` |
| **D** | Floods of calls, from a leaked token or anyone | **Gap:** no rate limit anywhere. | #387 |
| **E** | A member doing what only a lead, admin or owner may | Role checks in the module that does the work. | `sm/identity.py:212`, `:216`, `:250` |
| **E** | One member's memory steering another member's coding agent (B7) | Words only: the agent is told memory is information, not instructions, and personal memory is labelled. **Gap:** nothing bounds a memory's text in the prompt. | `sm/recall.py:29`; `sm/app.py:61`; `sm/service.py:82`; #389 |
| **E** | Rebinding a browser to a server that has no allowed hosts | Host header checked when `SHARED_MEMORY_ALLOWED_HOSTS` is set; production requires it. | `sm/app.py:1116`; `deploy/compose.yaml:32` |

## 2. Console JSON API: `/api`

| | Threat | Check | Where |
| --- | --- | --- | --- |
| **S** | Forged or replayed GitHub sign-in | A one-time state, stored as a hash, spent once within 10 minutes; the code is exchanged server-side; the account id must match a member of exactly one team. | `sm/console_sessions.py:67-75`, `:101-109`; `sm/identity.py:345` |
| **S** | Stolen or stale session | Cookie is HttpOnly, Secure on HTTPS, SameSite=Lax; every call checks the session isn't ended, idle 24 h, older than 7 days, or a removed member's. | `sm/console_api.py:294-301`; `sm/console_sessions.py:162-182`; `sm/config.py:36-37` |
| **T** | Cross-site request changing something | A changing call without `X-Shared-Memory-Console` gets 403; there are no CORS headers, so another site can't send it. | `sm/console_api.py:259-260` |
| **T** | The console writing memory | Never: it pins, unpins, decides challenges and retires (ADR-0009). Saving, editing and promoting exist only as MCP tools. | `sm/console_api.py:79` |
| **R** | A member denies a governance change | Sign-ins, refused sign-ins, project, lead, repository, access, member, admin and token changes are all audited. | `sm/console_sessions.py:95`, `:98`; `sm/console_api.py:321-433`, `:904-975` |
| **I** | Reading another team's or a restricted project's data | The same identity checks as MCP run beneath every call. | `sm/identity.py:604`, `:476` |
| **D** | Floods of calls | **Gap:** no rate limit (same as MCP). | #387 |
| **E** | A member managing members, tokens or ownership | Admin and owner checks. | `sm/identity.py:212`, `:216` |

## 3. Deploy path: GitHub Actions to the host

| | Threat | Check | Where |
| --- | --- | --- | --- |
| **S** | A fake host receiving the images, or a deploy from another branch | Host key pinned with `StrictHostKeyChecking`; the `production` environment is limited to `main`; only a push to `main` that passed Checks deploys. | `.github/workflows/deploy.yml:37-42`, `:78-85`; `docs/deployment.md:129` |
| **T** | The deploy key used for anything else | `restrict,command=` lets it run only `deploy.sh`, whose words are parsed, never run; the commit must be a full hash on `main`. | `docs/deployment.md:125`; `deploy/deploy.sh:184-189`, `:91`, `:97` |
| **T** | A moved action tag shipping a different image | **Gap:** third-party actions run by tag while the key is on disk, and the host doesn't check the images came from the commit. | #390 |
| **R** | Who deployed what | The Actions run records actor and commit; `deploy.sh` logs each step. | `.github/workflows/deploy.yml:65-67`; `deploy/deploy.sh:28` |
| **I** | Secrets leaking from the workflow | Read-only `GITHUB_TOKEN`; key and known hosts only in environment secrets, written mode 600. | `.github/workflows/deploy.yml:27-28`, `:77` |
| **D** | A bad release, or two deploys at once | One deploy at a time (workflow concurrency and `flock`); back up first; a release that isn't healthy is replaced by the one before; the backup reports unhealthy after 26 h without success. | `.github/workflows/deploy.yml:31-33`; `deploy/deploy.sh:94`, `:111`, `:116-122`; `deploy/backup/backup.sh:74-81` |
| **E** | A break-in to the server process becoming root | Rootless Docker on the live host. **Gap:** the image itself runs as root. | `deploy/deploy.sh:180`; #388 |

## Candidate gaps, judged

| Candidate | Verdict | Reason |
| --- | --- | --- |
| No rate limiting | **Filed #387** | A leaked token or a runaway agent can hold the workers; recall and search embed on the server. |
| Personal tokens never expire | Accepted | 256-bit, stored hashed, revoked on reissue and on removal (`sm/identity.py:307`, `:316`, `:377`); expiry would stop unattended coding agents without closing a real hole. |
| Image runs as root | **Filed #388** | Rootless Docker protects the live host only; a self-hosted server on ordinary Docker gets a root process. |
| Prompt injection through memory | **Filed #389** | The main content risk: one session's memory reaches every member's prompt, and nothing bounds its text. |
| `tools/list` without a token | Accepted | Presentation only; the schemas are public in the repository; calling needs a token. |
| Repository registration through `X-Shared-Memory-Repository` | Accepted | Only a member who already reaches the project can add one, the name is validated (`sm/identity.py:191`), and the list is only shown (`sm/identity.py:702`); a lead removes a wrong one. |
| Any member creates a project | Accepted | By design (the abilities table in `architecture.html`); audited (`sm/app.py:614`, `sm/console_api.py:321`). |
| `FORWARDED_ALLOW_IPS="*"` | Accepted | Set only in production, where the server publishes no port (`deploy/compose.yaml:45`); the development compose file leaves uvicorn's default of `127.0.0.1`. |
| DNS-rebinding only with `SHARED_MEMORY_ALLOWED_HOSTS` | Accepted | Production requires it (`deploy/compose.yaml:32`); elsewhere a rebound page still has no personal token, and the console cookie stays with its own host. |
| Third-party actions by tag (found here) | **Filed #390** | A moved tag runs with the deploy key on disk and builds the images the host runs. |

## Recommendation: `serve --host` defaults to `127.0.0.1`

`shared-memory serve` defaults to `--host 0.0.0.0` (`sm/cli.py:42`), so a run on a laptop listens on the whole network
over plain HTTP, usually without allowed hosts set. The image doesn't need the default: `Dockerfile:22` already passes
`--host 0.0.0.0`, and both compose files run that command. **Decision:** default to `127.0.0.1`, and drop the
`noqa: S104`. Tracked in #391; no code changes in this pull request.

Revisit this page in a spec's retro whenever a crossing in the trust-boundaries view changes.
