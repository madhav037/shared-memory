import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** A memory's Markdown set as printed text. Raw HTML in a memory is shown as text, never run. */
export function Prose({ children, testid }: { children: string; testid?: string }) {
  return (
    <div className="prose" data-testid={testid}>
      <Markdown remarkPlugins={[remarkGfm]}>{children}</Markdown>
    </div>
  );
}
