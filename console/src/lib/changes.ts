/**
 * What one memory would change about another, said in plain words.
 *
 * A challenge puts two memories side by side that were written separately, in different sessions, by different
 * people — so they are not versions of one text and a word-by-word comparison of them reads as noise. What a member
 * actually has to decide is what would be different if they accepted, which for a memory written as a list of
 * "label: value" lines can be said outright: this part changes from this to that, and these parts stay as they are.
 *
 * When neither memory is written that way there is nothing honest to summarise, and the reader is left to read both.
 */

export type Difference =
  | { kind: "changed"; label: string; from: string; to: string }
  | { kind: "added"; label: string; to: string }
  | { kind: "removed"; label: string; from: string };

export type Comparison = { differences: Difference[]; unchanged: string[] };

/** A line like "- Backend: Java with Spring Boot", which is how a decision memory usually sets out its parts. */
const PART = /^\s*[-*•]\s*([^:]{2,48}?)\s*:\s*(\S.*?)\s*$/;

/** Enough parts on a side to be worth comparing part by part rather than as prose. */
const ENOUGH = 2;

function parts(text: string): Map<string, { label: string; value: string }> {
  const found = new Map<string, { label: string; value: string }>();
  for (const line of text.split("\n")) {
    const match = PART.exec(line);
    if (!match) continue;
    const [, label, value] = match as unknown as [string, string, string];
    const key = label.toLowerCase();
    if (!found.has(key)) found.set(key, { label, value });
  }
  return found;
}

/**
 * The parts that would change, and the parts that would stay as they are. Null when neither memory is a list of
 * parts, which is when there is nothing to say that reading both wouldn't say better.
 */
export function whatChanges(before: string, after: string): Comparison | null {
  const now = parts(before);
  const offered = parts(after);
  if (now.size < ENOUGH && offered.size < ENOUGH) return null;

  const differences: Difference[] = [];
  const unchanged: string[] = [];
  for (const [key, part] of now) {
    const other = offered.get(key);
    if (other === undefined) {
      differences.push({ kind: "removed", label: part.label, from: part.value });
    } else if (other.value === part.value) {
      unchanged.push(part.label);
    } else {
      differences.push({ kind: "changed", label: part.label, from: part.value, to: other.value });
    }
  }
  for (const [key, part] of offered) {
    if (!now.has(key)) differences.push({ kind: "added", label: part.label, to: part.value });
  }
  return { differences, unchanged };
}
