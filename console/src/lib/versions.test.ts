import { describe, expect, it } from "vitest";

import type { MemoryVersion } from "../api/client";
import { agentLabel, inAgent, inForce, whatHappened } from "./versions";

const TITLE = "Use pnpm, not npm";

/** A version as the server records it: only the message and the author matter to what is said about it. */
function version(message: string, over: Partial<MemoryVersion> = {}): MemoryVersion {
  return {
    commit: "0123456789abcdef",
    at: "2026-09-01T09:00:00Z",
    author: "E1001",
    name: "Olive Owner",
    message,
    agent: null,
    ...over,
  };
}

describe("what a version did, from the message the server wrote", () => {
  it("reads the four prefixes the server writes", () => {
    expect(whatHappened(version(`Remember: ${TITLE}`), TITLE)).toBe("First written by Olive Owner");
    expect(whatHappened(version(`Edit: ${TITLE}`), TITLE)).toBe("Amended by Olive Owner");
    expect(whatHappened(version(`Promote: ${TITLE}`), TITLE)).toBe("Promoted by Olive Owner");
    expect(whatHappened(version(`Retire: ${TITLE}`), TITLE)).toBe("Retired by Olive Owner");
  });

  it("names the memory that took this one's place, when the message names another", () => {
    expect(whatHappened(version("Promote: Use bun"), TITLE)).toBe(
      "Superseded by “Use bun”, which Olive Owner promoted in its place",
    );
  });

  it("tells a retire challenge from a supersede challenge", () => {
    expect(whatHappened(version(`Accept challenge 3: retire ${TITLE}`), TITLE)).toBe(
      "Retired by Olive Owner, who accepted challenge 3",
    );
    expect(whatHappened(version("Accept challenge 4: Use bun"), TITLE)).toBe(
      "Superseded by “Use bun”, when Olive Owner accepted challenge 4",
    );
    expect(whatHappened(version(`Accept challenge 5: ${TITLE}`), TITLE)).toBe(
      "Took the place of the memory it challenged, when Olive Owner accepted challenge 5",
    );
  });

  it("says the message itself when the server writes one it does not know", () => {
    // This is the fallback the audit names: a prefix the server changes reads as raw text and nothing else.
    expect(whatHappened(version(`Archive: ${TITLE}`), TITLE)).toBe(`Archive: ${TITLE}, by Olive Owner`);
  });

  it("names the coding agent a change came through", () => {
    expect(whatHappened(version(`Remember: ${TITLE}`, { agent: "Codex" }), TITLE)).toBe(
      "First written by Olive Owner in Codex",
    );
    expect(whatHappened(version(`Remember: ${TITLE}`, { agent: "another agent" }), TITLE)).toBe(
      "First written by Olive Owner",
    );
  });
});

describe("which agent a change came from", () => {
  it("says nothing when the server recorded no agent", () => {
    expect(inAgent(null)).toBe("");
    expect(inAgent(undefined)).toBe("");
    expect(inAgent("")).toBe("");
  });

  it("says nothing when the server knew only that it was some other agent", () => {
    expect(inAgent("another agent")).toBe("");
    expect(agentLabel("another agent")).toBe("");
  });

  it("stands on its own, capitalised", () => {
    expect(agentLabel("Codex")).toBe("In Codex");
  });
});

describe("when a version was the text", () => {
  const first = version("Remember: x", { at: "2026-09-01T09:00:00Z" });
  const second = version("Edit: x", { at: "2026-09-03T11:30:00Z" });

  it("holds from one version until the next", () => {
    expect(inForce([first, second], 0)).toMatch(/^In force from .+ to .+$/);
  });

  it("holds still, when nothing has replaced it", () => {
    expect(inForce([first, second], 1)).toMatch(/^In force since /);
  });

  it("says what ended it, when something did", () => {
    expect(inForce([first, second], 1, "retired")).toMatch(/^Retired on /);
    expect(inForce([first, second], 1, "superseded")).toMatch(/^Superseded on /);
  });

  it("says so when a version stood for less than a minute", () => {
    const moment = version("Edit: x", { at: "2026-09-01T09:00:20Z" });
    expect(inForce([first, moment], 0)).toMatch(/^In force for under a minute/);
  });

  it("is empty for a version that is not there", () => {
    expect(inForce([], 0)).toBe("");
  });
});
