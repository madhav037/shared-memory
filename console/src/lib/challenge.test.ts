import { describe, expect, it } from "vitest";

import { asks, doubtsUrl, says } from "./challenge";

describe("what a challenge asks, in words", () => {
  it("names what a challenge that names no reason wants done to the memory", () => {
    expect(asks({ kind: "retire", reason: null })).toBe("retire it");
    expect(asks({ kind: "supersede", reason: null })).toBe("supersede it");
    expect(asks({ kind: "add", reason: null })).toBe("add a memory");
    expect(asks({ kind: "promote", reason: null })).toBe("promote it into department memory");
    expect(asks({ kind: "add", reason: null, foundation_name: "Billing rules" })).toBe(
      "add it to the Billing rules foundation",
    );
  });

  it("says a doubt by its reason", () => {
    expect(asks({ kind: "doubt", reason: "misled" })).toBe("doubt it: misled a session");
    expect(asks({ kind: "doubt", reason: "contradicts_code" })).toBe("doubt it: contradicts the code");
  });

  it("says what its raiser wants, after their name", () => {
    expect(says({ kind: "retire", reason: null })).toBe("wants to retire it");
    expect(says({ kind: "doubt", reason: "contradicts_code" })).toBe("doubts it: contradicts the code");
  });
});

describe("a memory's open doubts", () => {
  it("are linked to as the challenges against that one memory", () => {
    expect(doubtsUrl("projects/billing/shared/gotchas/tax.md")).toBe(
      "/challenges?path=projects%2Fbilling%2Fshared%2Fgotchas%2Ftax.md",
    );
  });
});
