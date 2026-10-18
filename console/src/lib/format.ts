const dayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const momentFormat = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const longDayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "long", year: "numeric" });

/** "17 September 2026" */
export function longDay(at: string | null | undefined): string {
  return at ? longDayFormat.format(new Date(at)) : "";
}

/** "17 Sep 2026" */
export function day(at: string | null | undefined): string {
  return at ? dayFormat.format(new Date(at)) : "";
}

/** "17 Sep 2026, 10:04" */
export function moment(at: string | null | undefined): string {
  return at ? momentFormat.format(new Date(at)) : "";
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Where a memory sits. The server's vocabulary, so anything naming levels is exhaustive against this. */
export const LEVEL_KEYS = ["team", "project", "personal"] as const;
export type Level = (typeof LEVEL_KEYS)[number];

/** What a memory is. The server's vocabulary, so anything naming types is exhaustive against this. */
export const TYPE_KEYS = ["convention", "decision", "architecture", "gotcha"] as const;
export type MemoryType = (typeof TYPE_KEYS)[number];

const LEVELS: Record<Level, string> = {
  team: "Team memory",
  project: "Project memory",
  personal: "Personal memory",
};

const TYPES: Record<MemoryType, string> = {
  convention: "Convention",
  decision: "Decision",
  architecture: "Architecture",
  gotcha: "Gotcha",
};

export function levelName(level: string): string {
  return LEVELS[level as Level] ?? level;
}

export function typeName(type: string): string {
  return TYPES[type as MemoryType] ?? type;
}

/** A memory file's lines, however it spells its line endings. */
function linesOf(source: string): string[] {
  return source.replace(/\r\n/g, "\n").split("\n");
}

/** Where a memory file's header ends: the line holding its closing fence, or -1 if it has no header. */
export function headerEnd(source: string): number {
  const lines = linesOf(source);
  return lines[0] === "---" ? lines.indexOf("---", 1) : -1;
}

/** The body of a memory file: everything after its header. */
export function bodyOf(source: string): string {
  const end = headerEnd(source);
  return (end < 0 ? source : linesOf(source).slice(end + 1).join("\n")).trim();
}

/** What the header of a memory file says, field by field, so a change to its standing can be named. */
export function headerOf(source: string): Map<string, string> {
  const lines = linesOf(source);
  const fields = new Map<string, string>();
  if (lines[0] !== "---") return fields;
  for (const line of lines.slice(1)) {
    if (line === "---") break;
    const at = line.indexOf(":");
    if (at > 0 && !line.startsWith(" ")) fields.set(line.slice(0, at), line.slice(at + 1).trim());
  }
  return fields;
}

/** Which level a memory path sits at: team memory, a project's accepted memory, or a member's personal memory. */
export function levelOf(path: string): string {
  if (path.startsWith("team/")) return "team";
  return path.split("/")[2] === "people" ? "personal" : "project";
}

export function folderUrl(path: string): string {
  return path ? `/files?folder=${encodeURIComponent(path)}` : "/";
}

export function memoryUrl(path: string): string {
  return `/memory?path=${encodeURIComponent(path)}`;
}

/** Where a project's active sessions are listed. */
export function sessionsUrl(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/sessions`;
}

/** Whether a folder is a topic: a folder of its own inside a type, as the server's console_memory.folder_kind has it. */
export function isTopic(path: string): boolean {
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "team") return parts.length > 2;
  if (parts[0] !== "projects" || parts.length < 4) return false;
  return parts[2] === "shared" ? parts.length > 4 : parts.length > 5;
}

/** A folder's name as the console shows it. A topic is named as it was written, often lowercase ("invoicing"), so it
 * takes sentence case to sit beside the types around it ("Conventions", "Invoicing"); every other folder is named as
 * the server names it. */
export function folderName(path: string, name: string): string {
  return isTopic(path) ? name.charAt(0).toUpperCase() + name.slice(1) : name;
}

/** The project a memory path or folder lives in, or nothing for team memory. */
export function projectIn(path: string): string | null {
  const parts = path.split("/");
  return parts[0] === "projects" && parts[1] ? parts[1] : null;
}

/** One piece of a notice as a person reads it: words, or a memory it names, to be shown by its title and linked. */
export type NoticePart = string | { title: string; path: string };

/** A memory a notice cites the way the server words it for an agent: its quoted title, then its path in brackets. */
const CITED_MEMORY = /"([^"]+)" \(([^()\s]+\.md)\)/g;

/**
 * A notice as a person reads it. The server words a notice for a coding agent, which acts on IDs: "Raj Raiser
 * (emp-raj) commented on your card 1 "Retry" in billing-00f655", or "E1001 promoted a memory in your name: "Use
 * pnpm" (projects/billing-00f655/shared/conventions/use-pnpm.md), …". Here a known member is their name alone,
 * whether the notice named them with their ID in brackets or by the ID alone at its start; a known project is its
 * name; a memory cited by title and path becomes a part of its own, for the page to link by its title; and the quotes
 * are curled. Anything it can't put a name to stays as the server said it.
 */
export function readableNotice(
  text: string,
  memberName: (memberId: string) => string | undefined,
  projects: Iterable<[string, string]>,
): NoticePart[] {
  const named = [...projects];
  const words = (piece: string, opening: boolean) => {
    let readable = piece.replace(/ \(([^()\s]+)\)/g, (whole, memberId: string) => (memberName(memberId) ? "" : whole));
    if (opening) readable = readable.replace(/^(\S+)(?= )/, (memberId) => memberName(memberId) ?? memberId);
    for (const [projectId, name] of named) {
      // A project ID is lowercase letters, figures and hyphens, so it needs no escaping inside a pattern.
      readable = readable.replace(new RegExp(`(?<![\\w-])${projectId}(?![\\w-])`, "g"), name);
    }
    return curled(readable);
  };
  const parts: NoticePart[] = [];
  let from = 0;
  for (const cited of text.matchAll(CITED_MEMORY)) {
    if (cited.index > from) parts.push(words(text.slice(from, cited.index), from === 0));
    parts.push({ title: cited[1]!, path: cited[2]! });
    from = cited.index + cited[0].length;
  }
  if (from < text.length) parts.push(words(text.slice(from), from === 0));
  return parts;
}

/** The first memory a notice names, if it names one. */
export function noticeMemory(parts: NoticePart[]): { title: string; path: string } | undefined {
  return parts.find((part): part is { title: string; path: string } => typeof part !== "string");
}

/** Straight quotes and apostrophes as printed ones: “these”, ‘these’ and it’s. */
export function curled(text: string): string {
  return text
    .replace(/(^|[\s([{—-])"/g, "$1“")
    .replace(/"/g, "”")
    .replace(/(^|[\s([{—-])'/g, "$1‘")
    .replace(/'/g, "’");
}
