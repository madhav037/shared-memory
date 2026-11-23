// Characters that carry text no reader sees (tag characters), reorder what is shown (bidi controls), or make different
// text look the same (zero-width characters). The server refuses them now; memories saved before may still hold them.
// ZWNJ and ZWJ (U+200C, U+200D) are left alone: emoji and Persian and Indic text need them.
const HIDDEN = /[\u{E0000}-\u{E007F}\u202A-\u202E\u2066-\u2069\u200E\u200F\u061C\u200B\u2060\uFEFF]/u;
const EVERY_HIDDEN = new RegExp(HIDDEN.source, "gu");

/** Whether any of these texts holds a character that hides or reorders text. */
export function hasHidden(...texts: (string | null | undefined)[]): boolean {
  return texts.some((text) => !!text && HIDDEN.test(text));
}

/** A text with each character that hides or reorders text drawn as its code, such as `<U+202E>`. */
export function visible(text: string): string {
  return text.replace(EVERY_HIDDEN, (one) => `<U+${one.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}>`);
}
