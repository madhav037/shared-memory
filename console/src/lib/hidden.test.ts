import { describe, expect, it } from "vitest";

import { hasHidden, visible } from "./hidden";

const tags = (words: string) => [...words].map((one) => String.fromCodePoint(0xe0000 + one.codePointAt(0)!)).join("");

describe("characters that hide or reorder text", () => {
  it("are drawn as their codes", () => {
    expect(visible(`Use pnpm.${tags("hi")}`)).toBe("Use pnpm.<U+E0068><U+E0069>");
    expect(visible("never\u202Eniam ot hsup")).toBe("never<U+202E>niam ot hsup");
    expect(visible("rm\u200B -rf \u2066x\u2069 \uFEFF\u200E\u200F\u061C")).toBe(
      "rm<U+200B> -rf <U+2066>x<U+2069> <U+FEFF><U+200E><U+200F><U+061C>",
    );
  });

  it("are found in any of the texts given", () => {
    expect(hasHidden("plain", null, `a${tags("x")}`)).toBe(true);
    expect(hasHidden("plain", undefined, "\u202A")).toBe(true);
    expect(hasHidden("plain", null, "")).toBe(false);
  });

  it("leave the joiners emoji and Persian and Indic text need", () => {
    const joined = "\u{1F469}\u200D\u{1F4BB} می\u200Cخواهم";

    expect(hasHidden(joined)).toBe(false);
    expect(visible(joined)).toBe(joined);
  });
});
