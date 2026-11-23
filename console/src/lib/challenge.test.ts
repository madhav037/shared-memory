import { describe, expect, it } from "vitest";

import { afterDeciding, asks, doubtsUrl, says, withNextPage } from "./challenge";

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

  it("says a level contradiction asks to keep the narrower memory as an exception", () => {
    expect(says({ kind: "level_contradiction", reason: null })).toBe("wants to keep theirs as an exception to it");
  });
});

describe("a memory's open doubts", () => {
  it("are linked to as the challenges against that one memory", () => {
    expect(doubtsUrl("projects/billing/shared/gotchas/tax.md")).toBe(
      "/challenges?path=projects%2Fbilling%2Fshared%2Fgotchas%2Ftax.md",
    );
  });
});

const one = (challenge_id: number, path = `projects/billing/shared/conventions/${challenge_id}.md`) => ({
  challenge_id,
  target: { path },
});

describe("the pages of waiting challenges", () => {
  it("puts the next page after the ones loaded, with its total and where the page after starts", () => {
    const loaded = { waiting: [one(1), one(2)], total: 5, next: 2 };

    expect(withNextPage(loaded, { waiting: [one(3), one(4)], total: 5, next: 4 })).toEqual({
      waiting: [one(1), one(2), one(3), one(4)],
      total: 5,
      next: 4,
    });
  });

  it("keeps the pages loaded beyond the first once one on them is decided, without it", () => {
    const loaded = { waiting: [one(1), one(2), one(3), one(4), one(5)], total: 6, next: 5 };
    const left = { waiting: [one(1), one(2)], total: 5, next: 2 };

    expect(afterDeciding(loaded, left, one(4), false)).toEqual({
      waiting: [one(1), one(2), one(3), one(5)],
      total: 5,
      next: 5,
    });
  });

  it("drops the others against the same memory when accepting one closed them", () => {
    const same = "projects/billing/shared/conventions/pnpm.md";
    const loaded = { waiting: [one(1), one(2), one(3, same), one(4, same)], total: 4, next: null };
    const left = { waiting: [one(1), one(2)], total: 2, next: 2 };

    expect(afterDeciding(loaded, left, one(3, same), true).waiting).toEqual([one(1), one(2)]);
    expect(afterDeciding(loaded, left, one(3, same), false).waiting).toEqual([one(1), one(2), one(4, same)]);
  });

  it("takes what deciding hands back as it is when that is every challenge left", () => {
    const loaded = { waiting: [one(1), one(2), one(3)], total: 3, next: null };
    const left = { waiting: [one(1), one(3)], total: 2, next: null };

    expect(afterDeciding(loaded, left, one(2), false)).toEqual(left);
  });

  it("goes on from where the first page ends when nothing beyond it was loaded", () => {
    const loaded = { waiting: [one(1), one(2)], total: 4, next: 2 };
    const left = { waiting: [one(2), one(3)], total: 3, next: 3 };

    expect(afterDeciding(loaded, left, one(1), false)).toEqual(left);
  });
});
