import type { Card, CardFields, MovedCard } from "../api/client";

export type Column = Card["column"];
export type Priority = Card["priority"];

/** The board's four columns, left to right, as the server names them. */
export const COLUMN_NAMES: Record<Column, string> = {
  to_do: "To do",
  doing: "Doing",
  blocked: "Blocked",
  done: "Done",
};

export const PRIORITY_NAMES: Record<Priority, string> = {
  high: "High",
  normal: "Normal",
  low: "Low",
};

function columnName(column: unknown): string {
  return COLUMN_NAMES[column as Column] ?? String(column);
}

/** Whether a card's due date has passed, is today, or neither. Both are dates written YYYY-MM-DD. */
export function dueness(due: string | null | undefined, today: string): "overdue" | "today" | null {
  if (!due) return null;
  if (due < today) return "overdue";
  return due === today ? "today" : null;
}

/** Today's date as a due date is written, in this computer's time zone. */
export function today(now: Date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** A card's file link, written repository:path. */
export function fileLink(entry: string): { repository: string; path: string } {
  const at = entry.indexOf(":");
  return { repository: entry.slice(0, at), path: entry.slice(at + 1) };
}

/** Where a project's board is: the board itself, one card open on it, or its archive. */
export function boardUrl(projectId: string, open: { card?: number; archive?: boolean } = {}): string {
  const query = new URLSearchParams();
  if (open.archive) query.set("view", "archive");
  if (open.card !== undefined) query.set("card", String(open.card));
  const written = query.toString();
  return `/projects/${encodeURIComponent(projectId)}/board${written ? `?${written}` : ""}`;
}

function listed(words: string[]): string {
  return words.length < 2 ? words.join("") : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

/** What the audit log's record of a change to a card says it did, in words. */
export function cardChange(detail: Record<string, unknown>, nameOf: (memberId: string) => string = (id) => id): string[] {
  const said: string[] = [];
  if (typeof detail.title === "string") said.push(`“${detail.title}”`);
  if (Array.isArray(detail.changed))
    said.push(`Changed its ${listed(detail.changed.map((field) => String(field).replace(/_/g, " ")))}`);
  if (detail.from !== undefined && detail.to !== undefined) {
    if (detail.from === detail.to)
      said.push(
        detail.position === 1 ? `To the top of ${columnName(detail.to)}` : `To place ${detail.position} in ${columnName(detail.to)}`,
      );
    else said.push(`From ${columnName(detail.from)} to ${columnName(detail.to)}`);
  } else if (detail.from !== undefined) {
    said.push(
      `From ${columnName(detail.from)}${typeof detail.assignee === "string" ? `, taken from ${nameOf(detail.assignee)}` : ""}`,
    );
  }
  if (typeof detail.blocked_reason === "string") said.push(detail.blocked_reason);
  if (typeof detail.waits_on === "number") said.push(`Waits on card ${detail.waits_on}`);
  return said;
}

type Placed = { column: Column; position: number };

/**
 * Where a card dropped on the board goes, as the position to ask for: in `column`, just above the card `before`, or
 * at the bottom when there is none (`undefined`). `null` when the drop leaves it where it was. Positions are the
 * server's, so they hold while the board is narrowed by filters: the card goes above `before` whatever is hidden.
 */
export function dropPlace(dragged: Placed, column: Column, before: Placed | null, lastInColumn = false): number | undefined | null {
  const staying = dragged.column === column;
  if (before === null) return staying && lastInColumn ? null : undefined;
  const position = staying && dragged.position < before.position ? before.position - 1 : before.position;
  return staying && position === dragged.position ? null : position;
}

/** A card's fields as a member fills them in. An empty due date is none; no assignee is `null`. */
export type CardDraft = {
  title: string;
  description: string;
  priority: Priority;
  labels: string[];
  due_date: string;
  assignee: string | null;
};

export function draftOf(card?: Card): CardDraft {
  return {
    title: card?.title ?? "",
    description: card?.description ?? "",
    priority: card?.priority ?? "normal",
    labels: card?.labels ?? [],
    due_date: card?.due_date ?? "",
    assignee: card?.assignee ?? null,
  };
}

/** What a filled-in card changes about the card it started from: only those fields are sent, so nothing else is touched. */
export function cardEdits(card: Card, draft: CardDraft): CardFields {
  const fields: CardFields = {};
  if (draft.title.trim() !== card.title) fields.title = draft.title;
  if (draft.description.trim() !== card.description) fields.description = draft.description;
  if (draft.priority !== card.priority) fields.priority = draft.priority;
  if (draft.labels.join("|") !== card.labels.join("|")) fields.labels = draft.labels;
  if (draft.due_date !== (card.due_date ?? "")) fields.due_date = draft.due_date;
  if (draft.assignee !== card.assignee) fields.assignee = draft.assignee ?? "";
  return fields;
}

/** What moving a card to Done did to the known issues it fixes, a sentence for each. */
export function fixedWords(moved: Pick<MovedCard, "known_issues_fixed" | "titles">): string[] {
  return moved.known_issues_fixed.map((one) => {
    const named = `the known issue “${moved.titles[one.path] ?? one.path.split("/").pop()}”`;
    return one.status === "retired"
      ? `Retired ${named}: the card that fixes it is done.`
      : `Asked the author of ${named} to retire it. Until they decide, it stands.`;
  });
}
