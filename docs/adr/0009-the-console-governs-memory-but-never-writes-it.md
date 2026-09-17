# The console governs memory but never writes or promotes it

From the console a member can pin, unpin, decide challenges and retire, but not write, edit or promote memory. Promotion depends on a member's own Claude judging whether memories contradict each other (ADR-0004), and a web page has no language model to do that.

## Consequences

- Memory is still written where it is learned, in a Claude session, which keeps the contradiction check in front of every promotion.
- A "just let me edit it here" button would either skip the check or need a model in the server, so it is a deliberate no rather than a missing feature.
