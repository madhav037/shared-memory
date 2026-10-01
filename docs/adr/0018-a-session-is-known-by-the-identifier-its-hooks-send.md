# A session is known by the identifier its coding agent's hooks send

The server had no session: MCP runs stateless (ADR-0013), and a caller was a member, a project and a repository. Locks and activity belong to a session, so the server now knows each one. A session is told apart by the identifier its coding agent already sends in every hook payload (Claude Code's `session_id`), kept per member and project. The session-start hook starts it and the briefing tells the agent that identifier; the tools that act for a session take it as `session`. An agent with no session-start hook is given one by `briefing`, which starts a session when called without one. Confirmed by the repo's human on 2026-10-01 (#220).

A session is active until its session-end hook, or until it has made no call for `session_idle_minutes` (30). Active is worked out from the clock on every read, in Postgres, with no background job, so every worker agrees.

## Considered options

- **A header on the MCP connection.** Rejected: no coding agent can put a value that changes per session into its MCP headers, which are written once in a committed file.
- **An MCP session.** Rejected: the server runs MCP stateless so that any worker can answer any call (ADR-0013), and the hooks, which are plain HTTP, would not carry it.

## Consequences

- Only a call that names the session keeps it active: every hook, and the tools that take `session`. A `search` or a `remember` names none. In an agent with hooks, every prompt counts, which is enough; in one without, a session stays active by calling the session tools.
- A session that calls again after going idle is active again from that call, but its activity and locks are gone and do not come back. It is told so once, on its next prompt.
- The identifier is whatever the agent sends, so it is only ever a name for the member's own session: it is kept per member, and one member's identifier never reaches another member's session.
- A hook does not say which coding agent sent it, so a session's coding agent is known only once one of its tool calls has reported it.
