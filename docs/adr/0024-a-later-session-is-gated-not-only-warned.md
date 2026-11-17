# A later session is gated, not only warned

A collision warning (#227) was information: two members could still both build the same payment form and spend twice the tokens. Now the later session's file edits on the colliding work are refused until every earlier session's member agrees, or stays silent for the project's wait (five minutes by default, set by its leads), or the later member says it is different work. Reading, searching and planning still go ahead. An earlier member's "no" keeps the gate until that session ends or goes idle. An urgent message turns it round: the earlier session is gated until its member answers. Confirmed by the repo's human on 2026-11-16.

## Considered options

- **Warn only, as before.** Rejected: an agent told about a collision usually carries on, and nobody finds out until the second pull request.
- **Ask first, without refusing edits.** Rejected by the repo's human in favour of a gate that cannot be ignored.
- **The earlier member must agree, with no wait.** Rejected: a member away from their desk would hold the later one up indefinitely.

## Consequences

- A collision found wrongly stops real work, so the later member can always lift it by saying it is different work, and that verdict and its score are recorded to tune the threshold (#338).
- Sessions that have ended or gone idle gate nobody; the later session is reminded of their recent work and given their handoff note instead.
- A member's own sessions warn each other but never gate each other.
- Coding agents with no hooks (Copilot in VS Code, Cursor on Windows) cannot be gated: their guidance states the rule, and the member is told at connect time.
- The gate refuses every file edit of the later session, not only edits of the files the earlier session touched or holds. Collisions are found from activities and prompts, usually as both sessions start, when the earlier one has touched little or nothing, so a gate narrowed to its files would let the duplicate work through exactly when it begins; and which files "the same work" will need can't be told from a path. The wait, a refusal that can become agree, and different work keep the cost of a wide gate small. Decided at the review of #507.
