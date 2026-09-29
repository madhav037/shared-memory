# Several server processes save, with their turns held in Postgres

One server process could use one core: Python runs one thread at a time, so under a team's load every call queued for it, whatever the other cores were doing. `shared-memory serve` now sets up the schema and the memory folder's repository once, then starts several uvicorn workers (`SHARED_MEMORY_WORKERS`, default 2) on the one port. Saves still take turns per area (ADR-0012), but the turns are Postgres advisory locks taken at the start of the save's own transaction, in the same fixed order, so every worker sees them and a worker that dies releases them with its connection. Moving `main` is guarded by a short advisory lock of its own. This replaces ADR-0012's "only one server process saves".

We rejected file locks next to the memory folder, which would tie the turns to one machine and to the OS releasing a dead holder's lock, and separate server containers behind Caddy, which change deployment more for the same gain.

## Consequences

- A worker that dies mid-save leaves its turns free but may leave files it wrote. Each save records the paths it will touch, in a marker committed before it writes, and clears it once it has landed or been undone. The next save to take that area's turn and find a marker puts those paths back to what `main` holds and indexes them again.
- The database connections (`SHARED_MEMORY_DATABASE_CONNECTIONS`, default 40) are split among the workers, so adding workers can't exceed what Postgres allows.
- Each worker keeps its own caches and loads its own copy of the embedding model. A cached memory file is checked by inode, time and size, so another worker's save is always noticed.
- Several machines are still out of scope: they would also need one memory folder they all share.
