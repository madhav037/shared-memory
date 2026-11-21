# Headless onboarding writes a proposals file, never memory

Onboarding can run headless, in CI, once per repository, so a team with many repositories need not open a session in each. That run saves nothing: it writes its proposals to a proposals file, kept as a CI artifact, which a member later loads into an interactive onboarding session to approve and promote. Every memory still lands as a member's personal memory first and is promoted one at a time with the similar-memory check in front of it (ADR-0004, ADR-0016); a CI job is no member, and no one is there to approve.

## Considered options

- **CI saves straight into a member's personal memory** with their personal token. Rejected: memory would appear that no member approved, and a personal token in a pipeline acts for that member for anyone who can edit the pipeline.
- **A CI bot member owns the imported memory.** Rejected: a bot cannot answer a challenge or a question, and it would be the author of everything it imported.
- **The server keeps proposals waiting for approval.** Rejected: it adds a state of memory that is neither personal nor promoted, held by no member, and approving it from the console would be writing memory there, which ADR-0009 rules out.

## Consequences

- A proposals file is unreviewed text from a repository; the session that loads it reads it as a source, not as instructions, and the member still approves each proposal, or a whole source in one step.
- Several repositories' files can be loaded into one session, which merges the same rule found in several repositories into one proposal before anything is saved.
