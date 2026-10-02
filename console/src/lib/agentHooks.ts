/**
 * What each coding agent does with the team's memory by itself, through the hooks its plugin or connection kit
 * gives it, and what its guidance asks it to do instead where it has no hook.
 *
 * Each entry is named as `BEFORE_EDIT_HOOK` and `GUIDANCE_ONLY` name it in src/shared_memory/connection.py, where an
 * agent's kit differs between its own variants (Copilot CLI and Copilot in VS Code; Cursor on macOS and Linux, and
 * on Windows). agentHooks.test.ts holds the two to each other.
 */
export interface AgentHooks {
  /** As connection.py names it. */
  name: string;
  /** The tab on Connect your agent it belongs to. */
  agent: string;
  /** A session-start hook briefs every session. */
  briefing: boolean;
  /** A prompt hook recalls the memory that matches each prompt. */
  recall: boolean;
  /** A before-edit hook takes each file's lock before an edit. */
  locks: boolean;
  /** A session-end hook ends the session. */
  sessionEnd: boolean;
}

const EVERY_HOOK = { briefing: true, recall: true, locks: true, sessionEnd: true };
const NO_HOOK = { briefing: false, recall: false, locks: false, sessionEnd: false };

export const AGENT_HOOKS: AgentHooks[] = [
  { name: "Claude Code", agent: "Claude Code", ...EVERY_HOOK },
  { name: "Codex", agent: "Codex", ...EVERY_HOOK },
  { name: "Copilot CLI", agent: "GitHub Copilot", ...EVERY_HOOK, recall: false },
  { name: "Copilot in VS Code", agent: "GitHub Copilot", ...NO_HOOK },
  { name: "Gemini CLI", agent: "Gemini CLI", ...EVERY_HOOK },
  { name: "Cursor on macOS and Linux", agent: "Cursor", ...EVERY_HOOK, recall: false },
  { name: "Cursor on Windows", agent: "Cursor", ...NO_HOOK },
  { name: "Devin Desktop", agent: "Devin Desktop", ...EVERY_HOOK },
  { name: "Cline", agent: "Cline", ...EVERY_HOOK },
];

/** The variants of one tab's coding agent, in the order the page shows them. */
export function hooksOf(agent: string): AgentHooks[] {
  return AGENT_HOOKS.filter((one) => one.agent === agent);
}

/** What happens for each of the four, said in a line each: by a hook, or by what the agent is asked to do. */
export function whatHappens(hooks: AgentHooks): { topic: string; hooked: boolean; said: string }[] {
  return [
    {
      topic: "Briefing",
      hooked: hooks.briefing,
      said: hooks.briefing
        ? "Every session starts with the briefing."
        : "The agent is asked to call briefing itself at the start of a session.",
    },
    {
      topic: "Recall",
      hooked: hooks.recall,
      said: hooks.recall
        ? "Memory that matches each prompt is recalled into it."
        : "The agent is asked to call search itself before answering how the codebase or team works.",
    },
    {
      topic: "Locks",
      hooked: hooks.locks,
      said: hooks.locks
        ? "A before-edit hook takes each file’s lock, and stops the edit while another session holds the file."
        : "Guidance only: the agent is asked to call take_lock itself before it edits a file.",
    },
    {
      topic: "Session end",
      hooked: hooks.sessionEnd,
      said: hooks.sessionEnd
        ? "A session-end hook ends the session, and its locks with it."
        : "No session-end hook: the session’s locks go when it goes idle.",
    },
  ];
}
