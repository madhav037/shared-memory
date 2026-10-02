import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { AGENT_HOOKS, hooksOf, whatHappens } from "./agentHooks";

/** A tuple of names in src/shared_memory/connection.py, as the server's kit and guidance name them. */
function namedInConnection(tuple: string): string[] {
  const source = readFileSync(new URL("../../../src/shared_memory/connection.py", import.meta.url), "utf8");
  const found = new RegExp(`^${tuple} = \\(([^)]*)\\)`, "m").exec(source);
  if (!found) throw new Error(`${tuple} is not in connection.py`);
  return [...found[1]!.matchAll(/"([^"]+)"/g)].map((name) => name[1]!);
}

describe("which coding agents have a before-edit hook", () => {
  it("are the ones connection.py gives one, and the rest are guidance only, as it says", () => {
    const hooked = AGENT_HOOKS.filter((one) => one.locks).map((one) => one.name);
    const guided = AGENT_HOOKS.filter((one) => !one.locks).map((one) => one.name);

    expect(hooked.sort()).toEqual(namedInConnection("BEFORE_EDIT_HOOK").sort());
    expect(guided.sort()).toEqual(namedInConnection("GUIDANCE_ONLY").sort());
  });
});

describe("what happens by itself in a coding agent", () => {
  it("says where a hook takes each lock, and where the agent is asked to call take_lock itself", () => {
    const [cli, vsCode] = hooksOf("GitHub Copilot");

    expect(whatHappens(cli!).find((one) => one.topic === "Locks")).toMatchObject({ hooked: true });
    expect(whatHappens(vsCode!).find((one) => one.topic === "Locks")?.said).toContain("call take_lock itself");
  });

  it("names a briefing, recall, locks and a session end for every variant of every agent", () => {
    for (const hooks of AGENT_HOOKS) {
      expect(whatHappens(hooks).map((one) => one.topic)).toEqual(["Briefing", "Recall", "Locks", "Session end"]);
    }
  });
});
