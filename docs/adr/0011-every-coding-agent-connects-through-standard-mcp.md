# Every coding agent connects through standard MCP; hooks are per-agent adapters

Shared Memory is no longer for Claude Code alone. Every coding agent connects to the one MCP endpoint the same way: the server's URL, the member's personal token as a bearer header, and the project and repository as headers committed in the repository's own files for that agent (ADR-0005). The server teaches any agent the workflow through its connection instructions and its tool descriptions, and gives the briefing through a tool and a prompt as well as through the session-start hook. Where an agent has hooks, they call the same two hook endpoints as Claude Code's, and the server answers in that agent's format. Hooks are an adapter per agent; the memory tools are the same for all.

We rejected a plugin per agent (each would duplicate the server's rules and drift), and putting the project in the URL (with OAuth, each project URL is its own resource, so a member would sign in once per project).

## Consequences

- An agent without hooks only uses memory when it chooses to, guided by the instructions, the tool descriptions and the repository's AGENTS.md section. That is weaker than a hook, and is why hooks stay wherever an agent has them.
- The server offers no OAuth discovery. Cursor ignores configured headers when a server offers OAuth, so signing in through the browser is a separate, later decision.
- The name an agent reports for itself is recorded with each change for the audit log, but never trusted for access.
