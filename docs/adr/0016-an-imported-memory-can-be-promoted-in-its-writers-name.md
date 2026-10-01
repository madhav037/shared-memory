# An imported memory can be promoted in its writer's name

Until onboarding, a memory's author was always the member whose session saved it. Onboarding imports passages that someone else wrote, so promote accepts an author: when git blame shows one person wrote the passage and that person is a member who can reach the project, they become the author of the promoted memory, and the importer and the source are recorded on it. Authorship decides who may retire a memory and who decides a challenge against it, and that say belongs to whoever wrote the words, not to whoever ran onboarding.

The member's coding agent runs the blame and names the member, by member ID or GitHub username; the server only checks that the member exists and can reach the project, because it has no access to the repository's history (ADR-0004 keeps judgement in the session for the same reason). An author is named only on promote. In personal memory an imported memory is simply the importer's, and every promote still runs the similar-memory check, one memory at a time.

## Considered options

- **The importer is always the author.** Rejected: whoever onboards a repository would decide every later challenge against rules they never wrote.
- **The server works out the author**, from a commit or an email address. Rejected: the server never sees the repository, and members carry a GitHub username, not the addresses they commit with.
- **A bulk import that sets authors in one call.** Rejected: it would skip the similar-memory check that promotion exists for.

## Consequences

- A member can find themselves the author of a memory they never saved. They are told in their next briefing, by whom and from which file, and the audit log names both the author and the importer.
- The session's blame is trusted, as its judgement of contradictions is. A wrongly named author retires or supersedes the memory like any other.
- A passage several people wrote, a writer who is not a member, and a source outside git keep the importer as author, with the writer's name noted in the body where it is known.
