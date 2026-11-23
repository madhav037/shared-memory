import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Amended } from "./Amended";
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

describe("an image in a member's text", () => {
  const image = "Look: ![the chart](/api/export?1) and on.";

  it("is shown as the Markdown it was written in, never fetched", () => {
    const page = set(image);

    expect(page).not.toContain("<img");
    expect(page).toContain("![the chart](/api/export?1)");
  });

  it("is never fetched in an amended text either", () => {
    const page = renderToString(
      createElement(Amended, { pieces: [{ kind: "same", text: image }], source: "version 2" }),
    );

    expect(page).not.toContain("<img");
    expect(page).toContain("![the chart](/api/export?1)");
  });
});
