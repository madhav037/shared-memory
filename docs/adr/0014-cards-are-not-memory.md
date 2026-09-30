# Cards are not memory: they live in Postgres, and the console edits them

A project's board holds work, not knowledge. A card is open or done, has an assignee, and is worth nothing once finished, while memory is a settled statement kept with its history. So cards live in Postgres, with every change in the audit log, rather than as files committed to git (ADR-0002, ADR-0003). And the console may add, edit, move and delete cards, although ADR-0009 keeps it from writing memory: that rule exists because promoting memory needs a coding agent to judge contradictions, and a card has none to judge.

## Consequences

- Moving a card is a row update, not a commit, so a busy board doesn't fill the memory's git history, and listing the board is one query.
- A card's past is its audit log entries, not diffs. Cards are backed up with the database, not the memory folder.
- ADR-0009 still holds for memory. Linking a known issue to a card, or retiring one when its card is done, goes through the memory rules: the console may retire, as it could before, and nothing else.
