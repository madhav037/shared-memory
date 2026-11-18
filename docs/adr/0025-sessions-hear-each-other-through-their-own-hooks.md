# Sessions hear each other through their own hooks

Members on different networks want their sessions to know what the others are doing as it happens. The server cannot call into a coding agent, so each session hears its news when it calls the server: a hook before every tool call, which also tells the server the session's activity, branch and the files it has touched, and the prompt hook. While an agent works that is a few seconds; an agent waiting for its member hears on the next prompt, and the member is told meanwhile by the console's Sessions page and a browser alert. Prompt text is never shared. Confirmed by the repo's human on 2026-11-16.

## Considered options

- **A proxy between the coding agent and its model's API**, on our server or on the member's machine. Rejected: it hears a model call at about the moment a tool hook fires, so it is no faster, while it sees all of a member's code and credentials, stops the agent working whenever it fails, and only fits agents whose API address can be changed. It would also go round ADR-0011.
- **Claude Code channels**, which push into a running session. Deferred to a spike: a research preview, Claude Code only, needing claude.ai login and a local process.

## Consequences

- A hook on every tool call is one more small call to the server per tool call.
- An idle agent cannot be reached; only its member can.
- Four agents hear their news on a hook after each tool instead (Gemini CLI's AfterTool, Copilot CLI's postToolUse, Cursor's and Devin Desktop's postToolUse/PostToolUse): their hook before a tool can stop it but takes no added context, so news given there would be thrown away. Their hook before a tool still reports the session's place and refuses gated or locked edits. Those hooks on every tool call have an allowance of their own under the rate limit, so a fast agent calling two per tool is not limited in ordinary work.
- Copilot CLI's hooks post to the server themselves and run no shell, so they cannot name the session's git branch: its sessions show their touched files but no branch.
