# Contradiction checks run in the member's own Claude, not on the server

When a memory is promoted, the server only finds similar memories; the member's own Claude judges whether they contradict and asks the member whether to supersede, keep both, or cancel. The server runs no language model (only a small local embedding model for search), so it adds no model cost and sends memory content nowhere new.

## Consequences

- The check is only as good as the member's session, and a careless or mistaken session can wave a real contradiction through. Challenges, history and undo are the safety net, not the check itself.
