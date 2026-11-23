import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { HiddenWarning, Told } from "./Told";

const BIDI = String.fromCodePoint(0x202e);

describe("what recall tells coding agents of a memory besides its body", () => {
  it("is its summary and its tied files, hidden characters drawn as their codes", () => {
    const page = renderToString(
      createElement(Told, { summary: `Send the lockfile first.${BIDI}`, tiedFiles: ["billing-api:package.json"] }),
    );

    expect(page).toContain("Send the lockfile first.&lt;U+202E&gt;");
    expect(page.replace("<!-- -->", "")).toContain("Tied to billing-api:package.json");
  });
});

describe("a warning of characters that hide or reorder text", () => {
  it("is given when any of the words holds one", () => {
    const page = renderToString(createElement(HiddenWarning, { texts: ["Installs", null, `Use pnpm.${BIDI}`] }));

    expect(page).toContain('data-testid="hidden-characters"');
  });

  it("is not given otherwise", () => {
    expect(renderToString(createElement(HiddenWarning, { texts: ["Installs", null, "Use pnpm."] }))).toBe("");
  });
});
