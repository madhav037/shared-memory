# Known issues go straight into project memory

A known issue is saved directly to project memory, skipping personal memory and promotion. Its whole value is warning every member's agent before it repeats the bug, and waiting for the author to promote it would leave teammates unwarned for exactly the time it matters. The check promotion exists for still runs: saving a known issue shows the member's coding agent the similar project memories, and it resolves them before the known issue lands (ADR-0004).

## Considered options

- **Personal first, then promote**, like every other memory. Rejected: teammates' agents keep hitting the bug until the author remembers to promote it.
- **Straight in with no check.** Rejected: duplicate known issues for one bug would pile up in every briefing.

## Consequences

- A known issue must name its symptom and a workaround (or say there is none), and it is at project level only for now.
- It is retired once fixed, normally by whoever moves its card to Done. If someone else wrote it, retiring it raises a challenge to its author, as retiring another author's memory always does.
