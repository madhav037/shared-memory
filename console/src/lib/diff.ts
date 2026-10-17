export type Piece = { kind: "same" | "insert" | "delete"; text: string };

const LIMIT = 4_000_000;

/**
 * What changed between two texts, word by word, the way an amended section is marked up:
 * words taken out, words put in, and everything else as it was.
 */
export function wordDiff(before: string, after: string): Piece[] {
  const a = before.split(/(\s+)/).filter((token) => token !== "");
  const b = after.split(/(\s+)/).filter((token) => token !== "");
  if (a.length * b.length > LIMIT) {
    return merge([
      { kind: "delete", text: before },
      { kind: "insert", text: after },
    ]);
  }

  // Longest common subsequence, filled from the end so the walk below reads forwards.
  const width = b.length + 1;
  const table = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * width + j] =
        a[i] === b[j]
          ? table[(i + 1) * width + j + 1]! + 1
          : Math.max(table[(i + 1) * width + j]!, table[i * width + j + 1]!);
    }
  }

  const pieces: Piece[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      pieces.push({ kind: "same", text: a[i]! });
      i += 1;
      j += 1;
    } else if (table[(i + 1) * width + j]! >= table[i * width + j + 1]!) {
      pieces.push({ kind: "delete", text: a[i]! });
      i += 1;
    } else {
      pieces.push({ kind: "insert", text: b[j]! });
      j += 1;
    }
  }
  for (; i < a.length; i += 1) pieces.push({ kind: "delete", text: a[i]! });
  for (; j < b.length; j += 1) pieces.push({ kind: "insert", text: b[j]! });
  return passages(pieces);
}

/**
 * What changed between two texts, a line at a time.
 *
 * Word-by-word is right for one text amended into the next, where most words stand and a few give way. Two texts
 * written separately share only stray words, and matching those shreds both into fragments that read as noise. Whole
 * lines keep each statement together: this line goes, this one comes in, these are the same in both.
 */
export function lineDiff(before: string, after: string): Piece[] {
  const a = before.split("\n");
  const b = after.split("\n");
  const width = b.length + 1;
  const table = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * width + j] =
        a[i] === b[j]
          ? table[(i + 1) * width + j + 1]! + 1
          : Math.max(table[(i + 1) * width + j]!, table[i * width + j + 1]!);
    }
  }

  const pieces: Piece[] = [];
  const put = (kind: Piece["kind"], line: string) => pieces.push({ kind, text: `${line}\n` });
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      put("same", a[i]!);
      i += 1;
      j += 1;
    } else if (table[(i + 1) * width + j]! >= table[i * width + j + 1]!) {
      put("delete", a[i]!);
      i += 1;
    } else {
      put("insert", b[j]!);
      j += 1;
    }
  }
  for (; i < a.length; i += 1) put("delete", a[i]!);
  for (; j < b.length; j += 1) put("insert", b[j]!);
  return merge(pieces);
}

/**
 * Word-by-word changes read as noise: "night.night Don't at". An amended passage is set as what was taken out,
 * then what was put in. Changes separated only by spaces, or by a single short word, join into one passage.
 */
function passages(pieces: Piece[]): Piece[] {
  const out: Piece[] = [];
  let at = 0;
  while (at < pieces.length) {
    if (pieces[at]!.kind === "same") {
      out.push(pieces[at]!);
      at += 1;
      continue;
    }
    let end = at;
    let look = at + 1;
    while (look < pieces.length) {
      const piece = pieces[look]!;
      if (piece.kind !== "same") {
        end = look;
        look += 1;
        continue;
      }
      const bridge = /^\s+$/.test(piece.text) || (piece.text.length <= 3 && !/\s/.test(piece.text));
      if (bridge && look + 1 < pieces.length) {
        look += 1;
        continue;
      }
      break;
    }
    let taken = "";
    let put = "";
    for (let place = at; place <= end; place += 1) {
      const piece = pieces[place]!;
      if (piece.kind !== "insert") taken += piece.text;
      if (piece.kind !== "delete") put += piece.text;
    }
    if (taken.trim()) out.push({ kind: "delete", text: taken.trimEnd() });
    if (taken.trim() && put.trim()) out.push({ kind: "same", text: " " });
    if (put.trim()) out.push({ kind: "insert", text: put.trimEnd() });
    const trailing = (taken.trim() ? taken : put).match(/\s+$/)?.[0];
    if (trailing) out.push({ kind: "same", text: trailing });
    at = end + 1;
  }
  return merge(out);
}

/** Runs of the same kind read as one change, and a lone space between two changes belongs to them. */
function merge(pieces: Piece[]): Piece[] {
  const merged: Piece[] = [];
  for (const piece of pieces) {
    const last = merged[merged.length - 1];
    if (last && last.kind === piece.kind) last.text += piece.text;
    else merged.push({ ...piece });
  }
  return merged;
}

export function changed(pieces: Piece[]): boolean {
  return pieces.some((piece) => piece.kind !== "same");
}

const words = (text: string) => text.split(/\s+/).filter(Boolean).length;

/**
 * What an offer would change in the memory it is offered in place of. Most offers are that memory amended (a time
 * moved, one part swapped) and read best word by word, like any amendment. An offer written afresh shares only stray
 * words with it, and matching those shreds both into noise, so when fewer than half the words stand, it is compared a
 * whole line at a time.
 */
export function offerDiff(before: string, after: string): Piece[] {
  const pieces = wordDiff(before, after);
  const standing = words(
    pieces
      .filter((piece) => piece.kind === "same")
      .map((piece) => piece.text)
      .join(" "),
  );
  const longer = Math.max(words(before), words(after));
  return longer === 0 || standing * 2 >= longer ? pieces : lineDiff(before, after);
}
