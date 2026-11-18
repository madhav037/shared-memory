# A session awaiting an answer stands by

ADR-0025 lets a session hear news only when it calls the server, so an agent waiting for its member never heard the answer it was waiting for: in the first demo of #507, Ben's gated session showed nothing when Asha agreed. Now a session that awaits an answer (its edit is gated, or it sent an urgent message or one whose answer its member wants) stands by. Where the coding agent can run a background command and is woken when it ends, the agent runs one against `/hooks/standby`; everywhere else it calls the `stand_by` tool, which the server holds open for a short time and the agent calls again. Either way the standby answers with the session's news as soon as there is any, delivered once through the same place as every hook's, or ends at the project's wait. Confirmed by the repo's human on 2026-11-18 (#521).

## Considered options

- **The sync tool for every agent.** Rejected: the agent's turn is held inside the call, so its member can only type by interrupting it, and each agent's tool timeout cuts the standby into short pieces. Where a background command can wake the agent, that costs nothing.
- **The background command only.** Rejected: Codex and Gemini CLI make the model poll a background command, and Cline and Devin Desktop document no wake-up, so their sessions would still hear nothing.
- **Push from the server** (Claude Code channels, MCP tasks or notifications). Deferred (#519): only Claude Code documents a route to the model, and it is in preview or beta.
- **Postgres LISTEN/NOTIFY to end a standby at once.** Rejected for now: a held request checking every 2 seconds works across the server's workers with nothing new to run, at the cost of up to 2 seconds' delay.

## Consequences

- The coding agents whose wake-up after a turn ends is not documented (Copilot in VS Code, Cursor, Copilot CLI) are given both, the background command first and the tool as a fallback, until a hand-check settles which their kit names first.
- One standby per session: a new one ends the old. The member's next prompt ends it too, since they have moved on.
- A waiting session costs one held request and one small query every 2 seconds.
- A standby that cannot reach the server is tried once more, then the agent tells its member.
