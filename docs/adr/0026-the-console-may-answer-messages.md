# The console may answer messages

ADR-0009 keeps the console from writing memory, because writing needs a coding agent to judge contradictions. Messages between sessions are not memory and need no such judgement, and the member who must answer within the project's wait is often away from their terminal while their agent sits idle. So from the console a member may read their sessions' messages, reply, and agree to or refuse a later session's request to go ahead. It still never saves, edits or promotes a memory, and handoff notes are written only by sessions or the server. Confirmed by the repo's human on 2026-11-16.

## Considered options

- **Read only.** Rejected: a gate's wait would usually run out before the member got back to a session.
