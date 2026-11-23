import { lineDiff } from "../lib/diff";
import { visible } from "../lib/hidden";

/**
 * One side of two memories' files compared line by line, word for word as a coding agent reads them: title, summary,
 * tied files and body alike. The lines only this side has are marked: taken out on the side as it stands now, put in
 * on the side offered.
 */
export function Compared({ before, after, side }: { before: string; after: string; side: "now" | "offered" }) {
  const away = side === "now" ? "insert" : "delete";
  const pieces = lineDiff(before.replace(/\r\n/g, "\n"), after.replace(/\r\n/g, "\n"));
  return (
    <pre className="source compared" data-testid="facing-source">
      {pieces
        .filter((piece) => piece.kind !== away)
        .map((piece, at) =>
          piece.kind === "same" ? (
            <span key={at}>{visible(piece.text)}</span>
          ) : piece.kind === "delete" ? (
            <del key={at}>{visible(piece.text)}</del>
          ) : (
            <ins key={at}>{visible(piece.text)}</ins>
          ),
        )}
    </pre>
  );
}
