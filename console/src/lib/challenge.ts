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
