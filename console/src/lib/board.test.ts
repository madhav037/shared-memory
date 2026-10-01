import { describe, expect, it } from "vitest";

import type { Card } from "../api/client";
import { boardUrl, cardChange, cardEdits, draftOf, dropPlace, dueness, fileLink, fixedWords } from "./board";

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

describe("where a dropped card goes", () => {
  it("goes above the card it is dropped on, in another column", () => {
    expect(dropPlace({ column: "to_do", position: 3 }, "doing", { column: "doing", position: 2 })).toBe(2);
  });

  it("goes to the bottom of a column when dropped below its cards", () => {
    expect(dropPlace({ column: "to_do", position: 1 }, "doing", null)).toBeUndefined();
  });

  it("moves up or down within its own column, counting without itself", () => {
    expect(dropPlace({ column: "to_do", position: 3 }, "to_do", { column: "to_do", position: 1 })).toBe(1);
    expect(dropPlace({ column: "to_do", position: 1 }, "to_do", { column: "to_do", position: 3 })).toBe(2);
  });

  it("stays put when dropped where it already is", () => {
    expect(dropPlace({ column: "to_do", position: 1 }, "to_do", { column: "to_do", position: 2 })).toBeNull();
    expect(dropPlace({ column: "to_do", position: 2 }, "to_do", { column: "to_do", position: 2 })).toBeNull();
    expect(dropPlace({ column: "to_do", position: 4 }, "to_do", null, true)).toBeNull();
  });
});

describe("what an edited card changes", () => {
  const card = {
    title: "Retry failed webhooks",
    description: "",
    priority: "normal",
    labels: ["webhooks"],
    due_date: "2026-10-15",
    assignee: null,
  } as Card;

  it("sends nothing when nothing was changed", () => {
    expect(cardEdits(card, draftOf(card))).toEqual({});
  });

  it("sends only the fields that changed, an empty due date or assignee to take it off", () => {
    expect(cardEdits(card, { ...draftOf(card), priority: "high", due_date: "" })).toEqual({ priority: "high", due_date: "" });
    expect(cardEdits({ ...card, assignee: "emp-2" }, { ...draftOf(card), labels: [] })).toEqual({ labels: [], assignee: "" });
  });
});

describe("what a card moved to Done did to its known issues", () => {
  const path = "projects/billing/known_issue/uploads-flake.md";

  it("says which were retired and whose authors were asked", () => {
    const titles = { [path]: "Uploads flake" };
    expect(fixedWords({ titles, known_issues_fixed: [{ status: "retired", path, challenge_id: null }] })).toEqual([
      "Retired the known issue “Uploads flake”: the card that fixes it is done.",
    ]);
    expect(fixedWords({ titles: {}, known_issues_fixed: [{ status: "challenge_raised", path, challenge_id: 4 }] })).toEqual([
      "Asked the author of the known issue “uploads-flake.md” to retire it. Until they decide, it stands.",
    ]);
  });

  it("says nothing when the card fixed none", () => {
    expect(fixedWords({ titles: {}, known_issues_fixed: [] })).toEqual([]);
  });
});
