import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { headerEnd } from "../lib/format";

/** A memory's Markdown set as printed text. Raw HTML in a memory is shown as text, never run. */
export function Prose({ children, testid }: { children: string; testid?: string }) {
  return (
    <div className="prose" data-testid={testid}>
      <Markdown remarkPlugins={[remarkGfm]}>{children}</Markdown>
    </div>
  );
}

/** How a memory is read: set as text, or word for word as a coding agent is given it. */
export type ReadingView = "text" | "source";

/** The choice between reading a memory as text and reading it as your agent reads it. */
export function ViewSwitch({ view, onChange }: { view: ReadingView; onChange: (view: ReadingView) => void }) {
  return (
    <div className="view-switch" role="tablist" aria-label="How to read it">
      <button
        type="button"
        role="tab"
        aria-selected={view === "text"}
        onClick={() => onChange("text")}
        data-testid="view-text"
      >
        Text
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={view === "source"}
        onClick={() => onChange("source")}
        data-testid="view-source"
      >
        As your agent reads it
      </button>
    </div>
  );
}

/** A memory word for word as a coding agent reads it: its header, if it is given one, then its body. */
export function Source({ text, testid = "memory-source" }: { text: string; testid?: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const closing = headerEnd(text);
  return (
    <pre className="source" data-testid={testid}>
      {lines.map((line, number) => (
        <span key={number} className={number <= closing ? "header-line" : undefined}>
          {line}
          {"\n"}
        </span>
      ))}
    </pre>
  );
}
