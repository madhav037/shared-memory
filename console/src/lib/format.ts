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

/** The body of a memory file: everything after its header. */
export function bodyOf(source: string): string {
  const match = source.replace(/\r\n/g, "\n").match(/^---\n[\s\S]*?\n---\n?([\s\S]*)$/);
  return (match?.[1] ?? source).trim();
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
