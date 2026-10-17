import type { Piece } from "./diff";

/** One change a text was given, as its numbered note under the text says it. */
export type Amendment = { marker: string; kind: "inserted" | "removed" | "substituted"; before?: string; after?: string };

/** What a mark stands for once the text around it has been set as Markdown. */
export type Mark = { kind: "open" | "close" | "removed"; index: number };

// Each mark travels through the Markdown parser as one private-use character, so the parser never mistakes it for
// syntax and it lands wherever the words around it land. The character says which amendment it belongs to, so a mark
// that ends up somewhere other than the text (a link's address, say) costs only that one mark.
const OPEN = 0xe000;
const CLOSE = 0xe800;
const REMOVED = 0xf000;
const SPAN = 0x800;
const MARK = /[-]/u;
const MARKS = /[-]/gu;

/** The syntax a line starts with: list bullets and numbers, task boxes, headings, quotes. The mark goes after it. */
const BLOCK_START = /^(?:[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?|[ \t]*#{1,6}[ \t]+|[ \t]*>[ \t]?)*/;
/** A list item's bullet or number: a whole list item taken out leaves its row of dots in the list. */
const LIST_ITEM_START = /^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+/;

export function markOf(char: string): Mark | null {
  const code = char.codePointAt(0) ?? 0;
  if (code >= OPEN && code < OPEN + SPAN) return { kind: "open", index: code - OPEN };
  if (code >= CLOSE && code < CLOSE + SPAN) return { kind: "close", index: code - CLOSE };
  if (code >= REMOVED && code < REMOVED + SPAN) return { kind: "removed", index: code - REMOVED };
  return null;
}

export function hasMarks(text: string): boolean {
  return MARK.test(text);
}

export function withoutMarks(text: string): string {
  return text.replace(MARKS, "");
}

const char = (base: number, index: number) => String.fromCodePoint(base + Math.min(index, SPAN - 1));

/**
 * A text as an amending version left it, as Markdown with every amendment marked where it falls, and the notes the
 * marks are keyed to. Words put in are enclosed by an opening and a closing mark; words taken out leave one mark.
 * Marks stay clear of the syntax a line starts with, so a list is still a list and a heading still a heading.
 */
export function amend(pieces: Piece[]): { markdown: string; notes: Amendment[] } {
  const notes: Amendment[] = [];
  let out = "";
  const atLineStart = () => out === "" || out.endsWith("\n");

  const putIn = (text: string, index: number) => {
    let rest = text;
    const lead = rest.match(/^\s*/)?.[0] ?? "";
    out += lead;
    rest = rest.slice(lead.length);
    if (atLineStart()) {
      const start = rest.match(BLOCK_START)?.[0] ?? "";
      out += start;
      rest = rest.slice(start.length);
    }
    const trail = rest.match(/\s*$/)?.[0] ?? "";
    out += char(OPEN, index) + rest.slice(0, rest.length - trail.length) + char(CLOSE, index) + trail;
  };

  const takeOut = (text: string, index: number) => {
    if (!atLineStart()) {
      out += char(REMOVED, index);
      return;
    }
    const item = text.match(LIST_ITEM_START)?.[0] ?? "";
    out += item + char(REMOVED, index) + (/\n\s*$/.test(text) ? "\n" : "");
  };

  for (let at = 0; at < pieces.length; at += 1) {
    const piece = { ...pieces[at]!, text: withoutMarks(pieces[at]!.text) };
    if (piece.kind === "same") {
      out += piece.text;
      continue;
    }
    const index = notes.length;
    const marker = `A${index + 1}`;
    // Words taken out and words put in their place, with nothing but space between, are one substitution.
    const gap = pieces[at + 1]?.kind === "same" && /^\s+$/.test(pieces[at + 1]!.text);
    const replacing =
      piece.kind === "delete"
        ? gap && pieces[at + 2]?.kind === "insert"
          ? pieces[at + 2]!
          : pieces[at + 1]?.kind === "insert"
            ? pieces[at + 1]!
            : null
        : null;
    if (replacing) {
      const after = withoutMarks(replacing.text);
      notes.push({ marker, kind: "substituted", before: piece.text.trim(), after: after.trim() });
      putIn(after, index);
      at += replacing === pieces[at + 2] ? 2 : 1;
    } else if (piece.kind === "delete") {
      notes.push({ marker, kind: "removed", before: piece.text.trim() });
      takeOut(piece.text, index);
    } else {
      notes.push({ marker, kind: "inserted", after: piece.text.trim() });
      putIn(piece.text, index);
    }
  }
  return { markdown: out, notes };
}
