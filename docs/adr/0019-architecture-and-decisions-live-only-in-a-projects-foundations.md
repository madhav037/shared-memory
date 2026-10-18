# Architecture and decisions live only in a project's foundations

A project's sources of truth were wherever someone happened to write them: an `ARCHITECTURE.md` in one repository, a decision saved as project memory, another restating it, a glossary nobody updated. Agents read whichever they found, and two could disagree without anyone noticing. Every project now has **foundations**: topics in project memory for its architecture, product, glossary and decisions, plus any extra a project lead adds. At project level, architecture and decision memories exist only inside their foundation. Promoting one, or adding to, superseding or retiring anything in a foundation, is a **foundation challenge**, decided by that foundation's **keeper** or a project lead. A foundation outweighs other project and team memory. Confirmed by the repo's human on 2026-10-18 (#294).

Projects only: team memory has no foundations. A foundation is memory like any other (ADR-0002), so the console still never writes it (ADR-0009). Assigning keepers and adding extras is governance and may be done from the console. Drafting and changing a foundation happens in a session, where the contradiction check runs (ADR-0004).

## Considered options

- **Leave the documents in the repository and keep memory in step with them.** Rejected: two copies drift, and agents in other repositories of the project can't read a file that isn't theirs. Onboarding imports the document and leaves a pointer in its place.
- **Let architecture and decision memories live anywhere and only suggest the foundation.** Rejected: the point is one place per source of truth. A suggestion leaves the second copy that causes the disagreement.
- **A separate approval queue for foundations.** Rejected: challenges already carry Reasoning, reach the decider's briefing and have a console screen (ADR-0017). A foundation challenge is a challenge, shown apart.

## Consequences

- Every promotion of a project memory of type architecture or decision waits on a keeper or project lead. That is slower than other promotions, on purpose.
- An author can no longer supersede their own memory freely inside a foundation: the change is a foundation challenge like anyone else's.
- A promotion that contradicts a foundation becomes a foundation challenge, and the foundation holds until it is decided.
- A missing foundation is drafted by any member's session and lands only once a keeper or project lead accepts it. The project's leads and keepers are told what is missing.
- Existing projects keep their architecture and decision memories where they are until a session proposes each into its foundation.
- A foundation with no keeper is decided by the project's leads. So is one whose keeper has left the team or lost access to the project.
