import { describe, expect, it } from "vitest";

import { boardUrl, cardChange, dueness, fileLink } from "./board";

describe("when a card is due, against today", () => {
  it("says a card due before today is overdue, and one due today is due today", () => {
    expect(dueness("2026-09-30", "2026-10-01")).toBe("overdue");
    expect(dueness("2026-10-01", "2026-10-01")).toBe("today");
  });

  it("says nothing of a card due later, or with no due date", () => {
    expect(dueness("2026-10-02", "2026-10-01")).toBeNull();
    expect(dueness(null, "2026-10-01")).toBeNull();
  });
});

describe("a file a card links to", () => {
  it("is its repository and its path within it", () => {
    expect(fileLink("billing-api:src/uploads.ts")).toEqual({ repository: "billing-api", path: "src/uploads.ts" });
  });
});

describe("a board's address", () => {
  it("opens the board, a card on it, or the archive", () => {
    expect(boardUrl("billing-1a2b3c")).toBe("/projects/billing-1a2b3c/board");
    expect(boardUrl("billing-1a2b3c", { card: 12 })).toBe("/projects/billing-1a2b3c/board?card=12");
    expect(boardUrl("billing-1a2b3c", { archive: true })).toBe("/projects/billing-1a2b3c/board?view=archive");
  });
});

describe("what the audit log says a change to a card did", () => {
  it("names the columns a card moved between", () => {
    expect(cardChange({ from: "to_do", to: "doing", position: 1 })).toEqual(["From To do to Doing"]);
  });

  it("names a reordering within one column as a new place", () => {
    expect(cardChange({ from: "to_do", to: "to_do", position: 1 })).toEqual(["To the top of To do"]);
    expect(cardChange({ from: "done", to: "done", position: 3 })).toEqual(["To place 3 in Done"]);
  });

  it("names what an edit changed, and the reason a card was blocked", () => {
    expect(cardChange({ changed: ["title", "due_date", "memories"] })).toEqual(["Changed its title, due date and memories"]);
    expect(cardChange({ from: "doing", to: "blocked", position: 1, blocked_reason: "Waiting on finance.", waits_on: 4 })).toEqual([
      "From Doing to Blocked",
      "Waiting on finance.",
      "Waits on card 4",
    ]);
  });

  it("names the card a change was made to, and a returned card's assignee", () => {
    expect(cardChange({ title: "Retry failed webhooks" })).toEqual(["“Retry failed webhooks”"]);
    expect(cardChange({ from: "doing", assignee: "emp-2" }, (id) => (id === "emp-2" ? "Dana Dev" : id))).toEqual([
      "From Doing, taken from Dana Dev",
    ]);
  });
});
