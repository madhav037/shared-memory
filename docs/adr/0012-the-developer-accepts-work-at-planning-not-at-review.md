# The developer accepts work at planning, not at review

One developer builds this codebase and coding agents write its code, faster than the developer can read it. So the developer's acceptance happens at planning: the acceptance criteria in each ticket are final once `to-tickets` runs with the developer present. After that, building runs unattended and merges into `dev` when CI is green, with no human diff review. The developer keeps track of what was built through two summaries. The architecture page (`docs/architecture.html`) is brought up to date at every spec's retro. A traceability comment on each spec issue maps every acceptance criterion to the test that proves it, and lists where the build left the plan.

## Considered options

- **Reading every diff** gives full ownership, but the developer could not keep up, and the review would quietly lapse to a skim.
- **Approving each ticket's tests before it is built** keeps acceptance with the developer per ticket. It also stalls every unattended run until the developer is back.
- **Reading only diffs that touch risky paths** (auth, personal tokens, deletion, history, deploy) was offered and not chosen. Security is covered by its own lane instead: a threat model, dependency scanning and linting in CI.

## Consequences

- An acceptance criterion missed or left vague at planning goes unchecked by a human until the spec's traceability comment. Planning has to be thorough, because it is the gate.
- The architecture page is load-bearing: it is how the developer knows the system. A spec isn't closed while its changes are missing from the page.
- `dev → main` stays the developer's call, so nothing reaches members unseen.
