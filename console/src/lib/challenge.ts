import type { ChallengeDetail } from "../api/client";

type Reason = NonNullable<ChallengeDetail["reason"]>;

/** A doubt's reason as its badge names it (CONTEXT.md: Reason). */
export const REASON_NAMES: Record<Reason, string> = {
  misled: "Misled a session",
  contradicts_code: "Contradicts the code",
};

/** What a challenge that names no reason asks done to the memory, by its kind. */
const KINDS: Record<string, string> = {
  retire: "retire it",
  supersede: "supersede it",
  add: "add a memory",
  promote: "promote it into department memory",
  level_contradiction: "keep theirs as an exception to it",
};

/** Enough of a challenge to say what it asks. */
type Asking = { kind: string; reason: Reason | null; foundation_name?: string | null };

/** What a challenge asks, in words that follow "to": "retire it", or for a doubt "doubt it: misled a session". */
export function asks(challenge: Asking): string {
  if (challenge.reason) return `doubt it: ${REASON_NAMES[challenge.reason].toLowerCase()}`;
  if (challenge.kind === "add" && challenge.foundation_name)
    return `add it to the ${challenge.foundation_name} foundation`;
  return KINDS[challenge.kind] ?? "supersede it";
}

/** What a challenge's raiser wants, after their name: "wants to retire it", "doubts it: contradicts the code". */
export function says(challenge: Asking): string {
  if (challenge.reason) return `doubts it: ${REASON_NAMES[challenge.reason].toLowerCase()}`;
  return `wants to ${asks(challenge)}`;
}

/** The challenges page showing only the challenges against one memory, its open doubts among them. */
export function doubtsUrl(path: string): string {
  return `/challenges?path=${encodeURIComponent(path)}`;
}

/** Enough of a waiting challenge to page through: its number, which orders the list, and what it is against. */
type Paged = { challenge_id: number; target: { path: string } };

/** The pages of waiting challenges loaded so far: the challenges, how many wait in all, and where the next page starts. */
type Pages<T extends Paged> = { waiting: T[]; total: number; next: number | null };

/** The loaded pages with the next page after them. */
export function withNextPage<T extends Paged>(loaded: Pages<T>, page: Pages<T>): Pages<T> {
  return { waiting: [...loaded.waiting, ...page.waiting], total: page.total, next: page.next };
}

/**
 * What stays loaded once a challenge is decided. Deciding hands back the first page as it stands now, which is the
 * truth for every challenge up to where that page ends; the pages loaded beyond it stay, without the one decided and,
 * when `closesOthers` (an accepted retire or supersede), without the others against the same memory.
 */
export function afterDeciding<T extends Paged>(
  loaded: Pages<T>,
  left: Pages<T>,
  decided: Paged,
  closesOthers: boolean,
): Pages<T> {
  const covered = left.next;
  if (covered === null) return { waiting: left.waiting, total: left.total, next: null };
  const beyond = loaded.waiting.filter((one) => one.challenge_id > covered);
  const kept = beyond.filter(
    (one) =>
      one.challenge_id !== decided.challenge_id && !(closesOthers && one.target.path === decided.target.path),
  );
  return { waiting: [...left.waiting, ...kept], total: left.total, next: beyond.length > 0 ? loaded.next : covered };
}
