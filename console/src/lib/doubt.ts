import type { InDoubtMark } from "../api/client";

type Reason = InDoubtMark["reasons"][number]["reason"];

/** A doubt's reason as its badge names it (CONTEXT.md: Reason). */
export const REASON_NAMES: Record<Reason, string> = {
  misled: "Misled a session",
  contradicts_code: "Contradicts the code",
};

/** What a reason says after "N say(s)". */
const SAYS: Record<Reason, string> = {
  misled: "it misled them",
  contradicts_code: "it contradicts the code",
};

/** What a memory's open doubts say, as a session's in-doubt line says it:
 * "2 say it misled them; 1 says it contradicts billing-api:src/tax.py:42". */
export function inDoubtWords(mark: InDoubtMark): string {
  return mark.reasons
    .map((each) => {
      const says = each.count === 1 ? "says" : "say";
      if (each.reason === "contradicts_code" && each.code_references.length > 0)
        return `${each.count} ${says} it contradicts ${each.code_references.join(", ")}`;
      return `${each.count} ${says} ${SAYS[each.reason]}`;
    })
    .join("; ");
}

/** The challenges page showing only the challenges against one memory. */
export function doubtsUrl(path: string): string {
  return `/challenges?path=${encodeURIComponent(path)}`;
}
