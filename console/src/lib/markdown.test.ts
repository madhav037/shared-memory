import { describe, expect, it } from "vitest";

import { tooIntricate } from "./markdown";

describe("Markdown too intricate to set as text", () => {
  it("lets ordinary Markdown through", () => {
    expect(tooIntricate("# Title\n\n> a quote\n> > nested\n\n- a\n  - b\n\n| a | b |\n|---|---|\n| 1 | 2 |")).toBe(false);
  });

  it("stops a line nested thousands deep", () => {
    expect(tooIntricate(">".repeat(11_999))).toBe(true);
    expect(tooIntricate("- ".repeat(500) + "x")).toBe(true);
  });

  it("stops a table thousands of columns wide", () => {
    expect(tooIntricate(`${"|a".repeat(2_500)}|\n${"|-".repeat(2_500)}|\n|x|`)).toBe(true);
  });
});
