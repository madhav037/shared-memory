import { hasHidden, visible } from "../lib/hidden";

/** What recall tells coding agents of a memory besides its body: its summary, and the files it is tied to. */
export function Told({ summary, tiedFiles }: { summary: string; tiedFiles: string[] }) {
  return (
    <>
      {summary && (
        <p className="told" data-testid="facing-summary">
          {visible(summary)}
        </p>
      )}
      {tiedFiles.length > 0 && (
        <p className="by" data-testid="facing-tied-files">
          Tied to {tiedFiles.map(visible).join(", ")}
        </p>
      )}
    </>
  );
}

/** A warning that words a coding agent reads hold characters that hide or reorder text, as memories saved before the
 * server refused them may. */
export function HiddenWarning({ texts }: { texts: (string | null | undefined)[] }) {
  if (!hasHidden(...texts)) return null;
  return (
    <p className="left-out" data-testid="hidden-characters">
      This holds characters that hide or reorder text, so what you see may not be what a coding agent reads. Each is
      drawn as its code, such as {"<U+202E>"}, where it falls.
    </p>
  );
}
