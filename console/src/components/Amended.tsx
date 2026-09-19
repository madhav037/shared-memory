import { useId, type ReactNode } from "react";

import type { Piece } from "../lib/diff";

type Amendment = { marker: string; kind: "inserted" | "removed" | "substituted"; before?: string; after?: string };

/**
 * A text as an amending version left it, marked up the way consolidated legislation is:
 * words put in sit in bold brackets with a numbered marker, words taken out leave a row of dots,
 * and every marker is keyed to a note under the text that says what the amendment did.
 */
export function Amended({ pieces, source, testid }: { pieces: Piece[]; source: string; testid?: string }) {
  const scope = `amend${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const notes: Amendment[] = [];
  const nodes: ReactNode[] = [];
  const mark = (marker: string) => (
    <sup className="marker" id={`${scope}-${marker}-ref`}>
      <a href={`#${scope}-${marker}`} aria-label={`Amendment ${marker}`}>
        {marker}
      </a>
    </sup>
  );

  for (let at = 0; at < pieces.length; at += 1) {
    const piece = pieces[at]!;
    if (piece.kind === "same") {
      nodes.push(<span key={at}>{piece.text}</span>);
      continue;
    }
    const marker = `A${notes.length + 1}`;
    const substituted =
      piece.kind === "delete" && pieces[at + 1]?.kind === "same" && pieces[at + 2]?.kind === "insert"
        ? pieces[at + 2]!
        : piece.kind === "delete" && pieces[at + 1]?.kind === "insert"
          ? pieces[at + 1]!
          : null;
    if (piece.kind === "delete" && substituted) {
      notes.push({ marker, kind: "substituted", before: piece.text, after: substituted.text });
      nodes.push(
        <ins key={at}>
          <span className="bracket" aria-hidden>
            [
          </span>
          {mark(marker)}
          {substituted.text}
          <span className="bracket" aria-hidden>
            ]
          </span>
        </ins>,
      );
      at += pieces[at + 1]?.kind === "same" ? 2 : 1;
    } else if (piece.kind === "delete") {
      notes.push({ marker, kind: "removed", before: piece.text });
      nodes.push(
        <del key={at}>
          <span className="repeal" aria-hidden>
            . . .
          </span>
          <span className="visually-hidden">{piece.text}</span>
          {mark(marker)}
        </del>,
      );
    } else {
      notes.push({ marker, kind: "inserted", after: piece.text });
      nodes.push(
        <ins key={at}>
          <span className="bracket" aria-hidden>
            [
          </span>
          {mark(marker)}
          {piece.text}
          <span className="bracket" aria-hidden>
            ]
          </span>
        </ins>,
      );
    }
  }

  return (
    <>
      <div className="amended" data-testid={testid}>
        {nodes}
      </div>
      {notes.length > 0 && (
        <ol className="amendments" aria-label="Amendments">
          {notes.map((note) => (
            <li key={note.marker} id={`${scope}-${note.marker}`}>
              <a className="marker-back" href={`#${scope}-${note.marker}-ref`}>
                {note.marker}
              </a>
              <span>
                {note.kind === "inserted" && <>Words inserted by {source}.</>}
                {note.kind === "removed" && (
                  <>
                    Words removed by {source}: <q>{note.before}</q>
                  </>
                )}
                {note.kind === "substituted" && (
                  <>
                    Words substituted by {source}, in place of <q>{note.before}</q>
                  </>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
