import { describe, expect, it } from "vitest";

import { doubtsUrl, inDoubtWords } from "./doubt";

describe("what a memory's open doubts say", () => {
  it("counts each reason, naming the code a contradiction quotes", () => {
    expect(
      inDoubtWords({
        count: 3,
        reasons: [
          { reason: "misled", count: 2, code_references: [] },
          { reason: "contradicts_code", count: 1, code_references: ["billing-api:src/tax.py:42"] },
        ],
      }),
    ).toBe("2 say it misled them; 1 says it contradicts billing-api:src/tax.py:42");
  });

  it("names every file and line quoted for one reason", () => {
    expect(
      inDoubtWords({
        count: 2,
        reasons: [
          {
            reason: "contradicts_code",
            count: 2,
            code_references: ["billing-api:src/tax.py:42", "billing-api:src/totals.py:7"],
          },
        ],
      }),
    ).toBe("2 say it contradicts billing-api:src/tax.py:42, billing-api:src/totals.py:7");
  });

  it("links to the challenges against one memory", () => {
    expect(doubtsUrl("projects/billing/shared/gotchas/tax.md")).toBe(
      "/challenges?path=projects%2Fbilling%2Fshared%2Fgotchas%2Ftax.md",
    );
  });
});
