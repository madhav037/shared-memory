import { describe, expect, it } from "vitest";

import { amend, markOf, withoutMarks } from "./amend";
import { lineDiff, wordDiff } from "./diff";

/** The marks written out, so where each falls can be read: ⟦1 … 1⟧ for words put in, ⟨1⟩ for words taken out. */
const shown = (markdown: string) =>
  [...markdown]
    .map((one) => {
      const mark = markOf(one);
      if (!mark) return one;
      const n = mark.index + 1;
      return mark.kind === "open" ? `⟦${n} ` : mark.kind === "close" ? ` ${n}⟧` : `⟨${n}⟩`;
    })
    .join("");

describe("marking an amended text before it is set", () => {
  it("marks words put in place of others as one substitution", () => {
    const { markdown, notes } = amend(wordDiff("Wiped every night.", "Wiped every night at 02:17 UTC."));

    expect(shown(markdown)).toBe("Wiped every ⟦1 night at 02:17 UTC. 1⟧");
    expect(notes).toEqual([{ marker: "A1", kind: "substituted", before: "night.", after: "night at 02:17 UTC." }]);
  });

  it("keeps a list item's bullet outside the brackets, so the list is still a list", () => {
    const { markdown } = amend(lineDiff("- Go\n- RabbitMQ", "- Go\n- Kafka"));

    expect(shown(markdown)).toBe("- Go\n- ⟦1 Kafka 1⟧\n");
  });

  it("leaves a list item taken out as its own row of dots", () => {
    const { markdown, notes } = amend(lineDiff("- Go\n- Redis\n- Kafka", "- Go\n- Kafka"));

    expect(shown(markdown)).toBe("- Go\n- ⟨1⟩\n- Kafka\n");
    expect(notes[0]).toEqual({ marker: "A1", kind: "removed", before: "- Redis" });
  });

  it("never runs words between two changes into one substitution", () => {
    const { markdown, notes } = amend([
      { kind: "same", text: "Ask " },
      { kind: "delete", text: "Olive" },
      { kind: "same", text: " before it ships to " },
      { kind: "insert", text: "staging" },
    ]);

    expect(withoutMarks(markdown)).toBe("Ask  before it ships to staging");
    expect(notes.map((note) => note.kind)).toEqual(["removed", "inserted"]);
  });

  it("drops anything in the text that could be mistaken for a mark", () => {
    const { markdown } = amend([{ kind: "same", text: "plain text" }]);

    expect(markdown).toBe("plain text");
  });
});
