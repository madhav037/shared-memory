import { describe, expect, it } from "vitest";

import { changed, lineDiff, wordDiff, type Piece } from "./diff";

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
