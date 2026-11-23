import { hasHidden, visible } from "./hidden";

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

/** The few parts of an HTML syntax tree the plugin below reads and adds to. */
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
const LISTED = 8; // left-out words named in the warning
const WORD = /[\p{L}\p{N}]+/gu;
const words = (value: unknown): string[] => (typeof value === "string" ? (value.match(WORD) ?? []) : []);
// An entity such as &amp; is set as the character it names, so its name is no word left out. Only the common ones:
// any `&word;` would let words be hidden as entities where the setting drops them.
const ENTITY = /&(?:#\d+|#x[\da-f]+|amp|lt|gt|quot|apos|nbsp);/gi;

const textOf = (node: Node): string =>
  node.type === "text" ? (node.value ?? "") : (node.children ?? []).map(textOf).join("");

/** What a link points at and its title, to set beside its label; none when the label already says it. */
function addressOf(link: Node): string | null {
  const properties = link.properties ?? {};
  if (properties.dataFootnoteRef !== undefined || properties.dataFootnoteBackref !== undefined) return null;
  const href = typeof properties.href === "string" ? properties.href : "";
  const title = typeof properties.title === "string" ? properties.title : "";
  const label = textOf(link).trim();
  if (!title && (!href || [label, `http://${label}`, `https://${label}`, `mailto:${label}`].includes(href))) return null;
  return title ? `${href} "${title}"`.trim() : href;
}

/**
 * A rehype plugin that keeps a memory set as text from hiding words a coding agent reads. Each link's address and
 * title are set beside its label, characters that hide or reorder text are drawn as their codes, and the text opens
 * with a warning when it holds such characters or when the setting leaves out words its Markdown holds: a link
 * definition, a footnote nothing refers to, words after a fence's language, a table cell past the header's columns,
 * an image's title.
 *
 * shortcut: words are compared by count, so a reference link labelled apart from its text (`[docs][1]`) warns
 * needlessly; read the Markdown's own syntax tree instead if that turns out to be common.
 */
export function showLeftOut() {
  return (tree: Node, file: { value?: unknown }) => {
    const shown = new Map<string, number>();
    const show = (value: unknown) => {
      for (const word of words(value)) shown.set(word, (shown.get(word) ?? 0) + 1);
    };
    const walk = (node: Node) => {
      if (node.type === "text" || node.type === "raw") {
        show(node.value);
        node.value = visible(node.value ?? "");
      }
      const properties = node.properties ?? {};
      const children = node.children ?? [];
      // Drawn without being text: a code block's language, a list's numbers, a ticked box, a footnote's label.
      if (node.tagName === "code" && Array.isArray(properties.className)) properties.className.forEach(show);
      if (node.tagName === "input" && properties.checked) show("x X");
      if (properties.dataFootnoteRef !== undefined) show(properties.href);
      if (node.tagName === "li") show(properties.id);
      // An image is drawn as the Markdown it was written in (MEMBER_TEXT): its alt text and address, not its title.
      if (node.tagName === "img") {
        show(properties.alt);
        show(properties.src);
        if (typeof properties.alt === "string") properties.alt = visible(properties.alt);
      }
      if (node.tagName === "ol") {
        const start = typeof properties.start === "number" ? properties.start : 1;
        children.filter((child) => child.tagName === "li").forEach((_, at) => show(String(start + at)));
      }
      for (let at = 0; at < children.length; at += 1) {
        const child = children[at]!;
        walk(child);
        const address = child.tagName === "a" ? addressOf(child) : null;
        if (address) {
          children.splice(at + 1, 0, element("span", { className: ["link-address"] }, [text(` (${visible(address)})`)]));
          show(address);
          at += 1;
        }
      }
    };
    walk(tree);

    const source = typeof file.value === "string" ? file.value.replace(ENTITY, " ") : "";
    const needed = new Map<string, number>();
    const left: string[] = [];
    for (const word of words(source)) {
      const count = (needed.get(word) ?? 0) + 1;
      needed.set(word, count);
      if (count > (shown.get(word) ?? 0) && !left.includes(word)) left.push(word);
    }
    const hidden = hasHidden(source);
    if (left.length === 0 && !hidden) return;
    const named = left.slice(0, LISTED).map((word) => `“${word}”`);
    const said = [
      left.length > 0 &&
        `Set as text, this leaves out words a coding agent reads: ${named.join(", ")}${left.length > LISTED ? " and more" : ""}.`,
      hidden && "It holds characters that hide or reorder text, drawn here as their codes, such as <U+202E>.",
    ];
    tree.children?.unshift(
      element("p", { className: ["hint", "left-out"], dataTestid: "left-out" }, [
        text(said.filter(Boolean).join(" ")),
      ]),
    );
  };
}
