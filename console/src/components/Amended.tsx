import { useId } from "react";
import Markdown, { type Options } from "react-markdown";
import remarkGfm from "remark-gfm";

import { amend, hasMarks, markOf, withoutMarks, type Amendment } from "../lib/amend";
import type { Piece } from "../lib/diff";

/**
 * A text as an amending version left it, set as printed text and marked up the way consolidated legislation is:
 * words put in sit in bold brackets with a numbered marker, words taken out leave a row of dots, and every marker is
 * keyed to a note under the text that says what the amendment did.
 */
export function Amended({ pieces, source, testid }: { pieces: Piece[]; source: string; testid?: string }) {
  const scope = `amend${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const { markdown, notes } = amend(pieces);
  const plugins = [[markAmendments, { notes, scope }]] as Options["rehypePlugins"];

  return (
    <>
      <div className="prose amended" data-testid={testid}>
        <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={plugins}>
          {markdown}
        </Markdown>
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

/** The few parts of an HTML syntax tree the marks are set into. */
type Node = {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: Node[];
};

const text = (value: string): Node => ({ type: "text", value });
const element = (tagName: string, properties: Record<string, unknown>, children: Node[]): Node => ({
  type: "element",
  tagName,
  properties,
  children,
});

/**
 * Turns the marks `amend` left in the text into the markup itself, once the Markdown has been set: brackets and a
 * marker where words were put in, a row of dots and a marker where words were taken out. Words put in that run across
 * a list item or a paragraph are enclosed piece by piece, with one pair of brackets around the whole.
 */
function markAmendments({ notes, scope }: { notes: Amendment[]; scope: string }) {
  const marker = (index: number) => {
    const name = `A${index + 1}`;
    return element("sup", { className: ["marker"], id: `${scope}-${name}-ref` }, [
      element("a", { href: `#${scope}-${name}`, ariaLabel: `Amendment ${name}` }, [text(name)]),
    ]);
  };
  const bracket = (value: string) => element("span", { className: ["bracket"], ariaHidden: "true" }, [text(value)]);

  return (tree: Node) => {
    // An opening mark whose closing one was lost (inside a link's address, say) would enclose the rest of the text.
    const closed = new Set<number>();
    const seen = (node: Node) => {
      if (node.type === "text" && node.value) {
        for (const one of node.value) {
          const mark = markOf(one);
          if (mark?.kind === "close") closed.add(mark.index);
        }
      }
      node.children?.forEach(seen);
    };
    seen(tree);

    let open: number | null = null;
    const set = (value: string): Node[] => {
      if (!hasMarks(value) && (open === null || !value.trim())) return [text(value)];
      const nodes: Node[] = [];
      let words = "";
      let enclosing: Node[] | null = open === null ? null : [];
      const flush = () => {
        if (!words) return;
        if (enclosing) enclosing.push(text(words));
        else nodes.push(text(words));
        words = "";
      };
      for (const one of value) {
        const mark = markOf(one);
        if (!mark) {
          words += one;
          continue;
        }
        flush();
        if (mark.kind === "open" && closed.has(mark.index) && open === null) {
          open = mark.index;
          enclosing = [bracket("["), marker(mark.index)];
        } else if (mark.kind === "close" && mark.index === open && enclosing) {
          enclosing.push(bracket("]"));
          nodes.push(element("ins", {}, enclosing));
          enclosing = null;
          open = null;
        } else if (mark.kind === "removed") {
          const taken = notes[mark.index]?.before ?? "";
          nodes.push(
            element("del", {}, [
              element("span", { className: ["repeal"], ariaHidden: "true" }, [text(". . .")]),
              element("span", { className: ["visually-hidden"] }, [text(taken)]),
              marker(mark.index),
            ]),
          );
        }
      }
      flush();
      if (enclosing && enclosing.length > 0) nodes.push(element("ins", {}, enclosing));
      return nodes;
    };

    const walk = (node: Node) => {
      if (node.properties) {
        for (const [key, value] of Object.entries(node.properties)) {
          if (typeof value === "string") node.properties[key] = withoutMarks(value);
        }
      }
      if (!node.children) return;
      node.children = node.children.flatMap((child) => {
        if (child.type === "text") return set(child.value ?? "");
        walk(child);
        return [child];
      });
    };
    walk(tree);
  };
}
