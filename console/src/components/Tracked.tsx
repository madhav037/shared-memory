import { collapse, type Piece } from "../lib/diff";

/**
 * Two texts shown as one, the way a marked-up draft reads: what the memory says now is struck through, what the offer
 * says instead follows it, and everything both agree on is left alone.
 *
 * A memory's own history is marked up the way consolidated legislation is — bracketed insertions keyed to numbered
 * notes — because there the reader is following one text through its amendments. A challenge is not that: it puts two
 * texts written separately side by side, and a reader deciding between them needs to see what goes and what comes in
 * without looking anything up. So nothing here is a marker, a bracket or a note: removed words are shown removed.
 * A long stretch both agree on is folded to a count of its lines, so the changes are what the eye lands on.
 */
export function Tracked({ pieces, testid }: { pieces: Piece[]; testid?: string }) {
  return (
    <div className="tracked" data-testid={testid}>
      <p className="tracked-key">
        <del>struck through</del> is what it says now · <ins>underlined</ins> is what this offer says instead
      </p>
      <p className="tracked-text">
        {collapse(pieces).map((piece, at) =>
          piece.kind === "folded" ? (
            <span key={at} className="tracked-folded" data-testid="tracked-folded">
              … {piece.lines} unchanged lines …{"\n"}
            </span>
          ) : piece.kind === "same" ? (
            <span key={at}>{piece.text}</span>
          ) : piece.kind === "delete" ? (
            <del key={at}>{piece.text}</del>
          ) : (
            <ins key={at}>{piece.text}</ins>
          ),
        )}
      </p>
    </div>
  );
}
