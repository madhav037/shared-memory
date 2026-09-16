# Memory lives on a central server, not in each repository

Members' sessions read and write memory through one server instead of committing `CLAUDE.md` or docs files to each repository. Git in the project repositories was too slow for "Claude just learned this" (commit and review), made repositories grow, gave no search once memory got large, and had no place for personal memory that the rest of the team can still read.

## Considered Options

- **Committed `CLAUDE.md` plus a `docs/` folder**: rejected for the reasons above.
- **Pointing Claude Code's built-in memory (`autoMemoryDirectory`) into the repository**: still git-bound, and still no search or personal/shared split. The built-in memory stays as local memory instead.
