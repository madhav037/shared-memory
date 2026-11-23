// Past these a renderer runs out of stack or hangs, and no memory needs them: such a text is shown word for word.
const LEADING = 200; // characters of quote, list and indent markers before a line's words
const PIPES = 100; // table cell borders on one line

/** Whether a text is nested too deep or a table too wide to be set as printed text. */
export function tooIntricate(text: string): boolean {
  return text.split("\n").some((line) => {
    const leading = /^[\s>*+\-\d.)]*/.exec(line)?.[0].length ?? 0;
    return leading > LEADING || line.split("|").length - 1 > PIPES;
  });
}
