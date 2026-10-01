# Coding standards

Read at review, not while implementing. These are the judgement calls no check can make; anything mechanical
belongs in a test or a linter instead of here. Naming is `CONTEXT.md`'s job and decisions are the ADRs'.

- **A refusal is told apart by its type.** Code that needs to treat one refusal differently catches a subclass of
  `Refused` or reads a field on it. Matching on the words of a message breaks the moment the wording improves.
- **One module owns each table.** A module that needs to know who leads a project or who may reach it asks
  `Identity`; it reads only the tables it owns.
- **A limit is named once.** A length, a count or a number of days lives in one constant, and the console reads it
  from the API's description. A literal repeated in a second file is the smell.
- **What crosses a module's interface is typed.** A dataclass or a model, so mypy sees its fields. A plain dict is
  for JSON at the edge.
- **A method does one job.** One that both validates, decides permission, writes and notifies is several methods
  behind one name.
- **Build what the spec asks.** A tool, route or option the originating issue doesn't name is filed as an issue.
