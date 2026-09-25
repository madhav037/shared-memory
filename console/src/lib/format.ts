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

/** The project a memory path or folder lives in, or nothing for team memory. */
export function projectIn(path: string): string | null {
  const parts = path.split("/");
  return parts[0] === "projects" && parts[1] ? parts[1] : null;
}
