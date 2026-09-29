import { describe, expect, it } from "vitest";

import { changed, collapse, lineDiff, wordDiff, type Piece } from "./diff";

/** One side of the comparison, read back: what the pieces say the text was, or became. */
const side = (pieces: Piece[], leaving: Piece["kind"]) =>
  pieces
    .filter((piece) => piece.kind !== leaving)
    .map((piece) => piece.text)
    .join("");

describe("word by word, for one text amended into the next", () => {
  it("leaves a text that did not change alone", () => {
    const pieces = wordDiff("Use pnpm, not npm", "Use pnpm, not npm");

    expect(changed(pieces)).toBe(false);
    expect(side(pieces, "insert")).toBe("Use pnpm, not npm");
  });

  it("marks what was taken out and what was put in", () => {
    const pieces = wordDiff("The database is wiped every night.", "The database is wiped at 02:17 UTC.");

    expect(changed(pieces)).toBe(true);
    expect(side(pieces, "insert")).toContain("every night.");
    expect(side(pieces, "delete")).toContain("at 02:17 UTC.");
    expect(side(pieces, "insert")).not.toContain("02:17");
  });

  it("gives up on word-by-word for two texts too long to compare that way", () => {
    const one = Array.from({ length: 1500 }, (_, place) => `word${place}`).join(" ");
    const other = Array.from({ length: 1500 }, (_, place) => `other${place}`).join(" ");

    expect(wordDiff(one, other).map((piece) => piece.kind)).toEqual(["delete", "insert"]);
  });
});

describe("line by line, for two texts written separately", () => {
  const before = "- Language: Go\n- Database: Postgres\n- Queue: RabbitMQ";
  const after = "- Language: Go\n- Database: Postgres\n- Queue: Kafka";

  it("keeps each statement whole rather than shredding it into words", () => {
    const pieces = lineDiff(before, after);

    expect(pieces.filter((piece) => piece.kind === "delete").map((piece) => piece.text)).toEqual([
      "- Queue: RabbitMQ\n",
    ]);
    expect(pieces.filter((piece) => piece.kind === "insert").map((piece) => piece.text)).toEqual(["- Queue: Kafka\n"]);
  });

  it("reads back as both texts", () => {
    const pieces = lineDiff(before, after);

    expect(side(pieces, "insert").trimEnd()).toBe(before);
    expect(side(pieces, "delete").trimEnd()).toBe(after);
  });

  it("runs of one kind read as one change", () => {
    const pieces = lineDiff("one\ntwo\nthree", "one");

    expect(pieces.filter((piece) => piece.kind === "delete")).toHaveLength(1);
    expect(pieces.filter((piece) => piece.kind === "delete")[0]?.text).toBe("two\nthree\n");
  });
});

describe("collapsing what did not change", () => {
  const lines = (from: number, to: number) =>
    Array.from({ length: to - from + 1 }, (_, place) => `line ${from + place}`).join("\n");

  it("folds a long unchanged stretch between two changes, keeping a line either side", () => {
    const before = `first\n${lines(1, 6)}\nlast`;
    const after = `FIRST\n${lines(1, 6)}\nLAST`;

    const shown = collapse(lineDiff(before, after));

    expect(shown.map((piece) => piece.kind)).toEqual(["delete", "insert", "same", "folded", "same", "delete", "insert"]);
    expect(shown[2]).toEqual({ kind: "same", text: "line 1\n" });
    expect(shown[3]).toEqual({ kind: "folded", lines: 4 });
    expect(shown[4]).toEqual({ kind: "same", text: "line 6\n" });
  });

  it("folds the unchanged opening and close down to the line next to the change", () => {
    const shown = collapse(lineDiff(`${lines(1, 5)}\nold\n${lines(6, 10)}`, `${lines(1, 5)}\nnew\n${lines(6, 10)}`));

    expect(shown[0]).toEqual({ kind: "folded", lines: 4 });
    expect(shown[1]).toEqual({ kind: "same", text: "line 5\n" });
    expect(shown[4]).toEqual({ kind: "same", text: "line 6\n" });
    expect(shown[5]).toEqual({ kind: "folded", lines: 4 });
  });

  it("leaves a short unchanged stretch alone, since folding one line hides nothing worth hiding", () => {
    const pieces = lineDiff("a\nsame 1\nsame 2\nsame 3\nb", "A\nsame 1\nsame 2\nsame 3\nB");

    expect(collapse(pieces)).toEqual(pieces);
  });
});
