# The console may ask and answer questions

ADR-0009 keeps the console from writing memory, because writing needs a coding agent to judge contradictions. A question about a memory, and its answers, are not memory: they need no such judgement, and the author asked is often reading the memory in the console, not in a session. So from the console a member may ask a memory's author a question and answer one asked of them. If an answer means the memory should change, the author still edits it in a session; the console never saves, edits or promotes a memory. Following ADR-0026, which let the console answer messages. Confirmed by the repo's human on 2026-11-19.

## Considered options

- **Read only.** Rejected: a member reading a memory in the console would have to open a session just to ask about it, and an author away from their terminal couldn't answer within the seven days before a question goes to the leads.
