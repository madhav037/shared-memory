// Past these a renderer runs out of stack or hangs, and no memory needs them: such a text is shown word for word.
const NESTING = 100; // quote and list markers opening one line
const PIPES = 100; // table cell borders on one line

// One of the quote and list markers a line opens with: `>`, or `-`, `*`, `+`, `1.` or `1)` followed by a space. A rule
// of dashes, or a run of spaces or digits, is not nesting.
const MARKER = /\s*(?:>|[-*+]\s|\d+[.)]\s)/y;

/** Whether a text is nested too deep or a table too wide to be set as printed text. */
export function tooIntricate(text: string): boolean {
  return text.split("\n").some((line) => {
    let markers = 0;
    MARKER.lastIndex = 0;
    while (markers <= NESTING && MARKER.test(line)) markers += 1;
    return markers > NESTING || line.split("|").length - 1 > PIPES;
  });
}
