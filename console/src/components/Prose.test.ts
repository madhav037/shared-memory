import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Prose } from "./Prose";

const set = (text: string) => renderToString(createElement(Prose, { children: text }));

describe("a memory set as text", () => {
  it("is shown word for word when it is nested too deep to set", () => {
    expect(set(">".repeat(11_999))).toContain("shown-word-for-word");
  });

  it("is set as text otherwise", () => {
    const page = set("> a quote");

    expect(page).toContain("<blockquote>");
    expect(page).not.toContain("shown-word-for-word");
  });
});
