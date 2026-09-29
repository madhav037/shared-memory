# Saves take turns per area, and commits are built in-process

A save used to wait for every other save on the server: one lock around writing the files, running the git CLI and indexing, about 7 saves a second in all, so a team's coding agents saving at once waited seconds each. Now saves take turns only within an area (the team memory, one project's project memory, or one member's personal memory in one project). A save that touches several areas, such as a promotion, takes their turns in one fixed order. Saves still share one git repository (ADR-0003): each builds its commit in memory with libgit2 (pygit2), with no git index file, and moves `main` with a compare-and-swap. If another area moved `main` first, it builds on top and tries again. Its paths never overlap the other area's, so the retry can't conflict.

We rejected a repository per project: team memory would need its own repository, a promotion into team memory would have to land in two repositories at once, and backups and history would split. We rejected keeping the git CLI with an index file per save, because starting its processes was most of a save's time.

## Consequences

- Moving `main` is a save's last step, after its database work is ready to commit. A failure before it leaves `main` untouched. If the database then fails to commit, a revert commit puts the files back. `main` is never reset, because other areas' commits may already sit on top.
- A folder's `index.md` is written only when its listing changes. Otherwise every save would rewrite the folders shared by every area, and they would take turns again.
- The git index file in the memory folder is not kept up to date; the memory files and the commits on `main` are what count.
- Only one server process saves. Several servers would need the turns held somewhere they all share, which is out of scope for now.
