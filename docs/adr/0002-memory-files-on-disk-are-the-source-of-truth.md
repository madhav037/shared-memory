# Memory files on the server's disk are the source of truth

Each memory is a Markdown file on the server's file system. Postgres holds only members, tokens, projects, fast-changing state (locks, challenges, activity, last use) and a search index that contains no readable memory content and can be rebuilt from the files at any time. We chose this so memory stays plain, portable, human-readable files, over storing memory content in database rows shown as a folder tree.

## Consequences

- Every change must go through the server; editing files directly on disk is not supported, because it would leave the search index and history out of step (a `reindex` command exists for repair).
