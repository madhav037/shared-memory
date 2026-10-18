import { Select } from "@mantine/core";
import { useState } from "react";

/** Every coding agent a repository can connect, in the one order the console lists them on every page. */
export const AGENT_NAMES = [
  "Claude Code",
  "Codex",
  "GitHub Copilot",
  "Gemini CLI",
  "Cursor",
  "Devin Desktop",
  "Cline",
] as const;

export type AgentName = (typeof AGENT_NAMES)[number];

const REMEMBERED = "shared-memory:agent";

/** The agent this viewer last chose, so Settings and Connect your agent open on it; storage may be blocked. */
function remembered(): string {
  try {
    const stored = window.localStorage.getItem(REMEMBERED);
    if (stored && (AGENT_NAMES as readonly string[]).includes(stored)) return stored;
  } catch {
    // A private window or blocked site data: start from the first agent.
  }
  return AGENT_NAMES[0];
}

/** The coding agent this viewer is looking at, remembered in their browser when it can be. */
export function useChosenAgent(): [string, (agent: string) => void] {
  const [agent, setAgent] = useState(remembered);
  const choose = (next: string) => {
    setAgent(next);
    try {
      window.localStorage.setItem(REMEMBERED, next);
    } catch {
      // Not remembered, but still chosen for this visit.
    }
  };
  return [agent, choose];
}

/** One labelled choice of coding agent, in place of a row of tabs that wraps on a phone. */
export function AgentSelect({ agent, onChange }: { agent: string; onChange: (agent: string) => void }) {
  return (
    <Select
      label="Agent"
      data={[...AGENT_NAMES]}
      value={agent}
      onChange={(value) => value && onChange(value)}
      allowDeselect={false}
      className="agent-select"
      data-testid="agent-choice"
    />
  );
}
