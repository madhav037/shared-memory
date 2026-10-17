import { Button, Select, TagsInput, TextInput, Textarea } from "@mantine/core";
import { useState } from "react";

import { Refusal } from "./Bits";
import { PRIORITY_NAMES, type CardDraft, type Priority } from "../lib/board";

type Choice = { value: string; label: string };

/**
 * A card's fields, to fill in: for a new card, or one being edited. A refusal is shown in the server's words, with
 * what was typed left in place.
 */
export function CardForm({
  initial,
  labels,
  assignees,
  action,
  onSubmit,
  onCancel,
}: {
  initial: CardDraft;
  /** Every label already on the board, offered so that labels don't drift into near-duplicates. */
  labels: string[];
  /** Who the card can be given to; left out where a card has no assignee to choose, as when it is added. */
  assignees?: Choice[];
  action: string;
  onSubmit: (draft: CardDraft) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [refused, setRefused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (fields: Partial<CardDraft>) => setDraft((was) => ({ ...was, ...fields }));

  return (
    <form
      className="card-form"
      data-testid="card-form"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setRefused(null);
        try {
          await onSubmit(draft);
        } catch (problem) {
          setRefused((problem as Error).message);
          setBusy(false);
        }
      }}
    >
      {refused && <Refusal testid="card-form-refused">{refused}</Refusal>}
      <TextInput
        label="Title"
        required
        data-autofocus
        value={draft.title}
        onChange={(event) => set({ title: event.currentTarget.value })}
        data-testid="card-title"
      />
      <Textarea
        label="Description"
        autosize
        minRows={3}
        maxRows={12}
        value={draft.description}
        onChange={(event) => set({ description: event.currentTarget.value })}
        data-testid="card-description"
      />
      <div className="card-form-pair">
        <Select
          label="Priority"
          allowDeselect={false}
          value={draft.priority}
          data={Object.entries(PRIORITY_NAMES).map(([value, label]) => ({ value, label }))}
          onChange={(value) => value && set({ priority: value as Priority })}
          data-testid="card-priority"
        />
        <TextInput
          label="Due date"
          type="date"
          value={draft.due_date}
          onChange={(event) => set({ due_date: event.currentTarget.value })}
          data-testid="card-due-date"
        />
      </div>
      <TagsInput
        label="Labels"
        description="Reuse a label already on the board where one fits."
        value={draft.labels}
        data={labels}
        onChange={(value) => set({ labels: value })}
        data-testid="card-labels"
      />
      <TagsInput
        label="Memories"
        description="The path of each memory the card is about, as its page in the console shows it."
        placeholder={draft.memories.length ? undefined : "projects/…/shared/decisions/….md"}
        value={draft.memories}
        splitChars={[",", " "]}
        onChange={(value) => set({ memories: value })}
        data-testid="card-memory-links"
      />
      <TagsInput
        label="Files"
        description="Each file written repository:path."
        placeholder={draft.files.length ? undefined : "e.g. billing-api:package.json"}
        value={draft.files}
        splitChars={[","]}
        onChange={(value) => set({ files: value })}
        data-testid="card-file-links"
      />
      {assignees && (
        <Select
          label="Assignee"
          placeholder="No assignee"
          clearable
          searchable
          value={draft.assignee}
          data={assignees}
          onChange={(value) => set({ assignee: value })}
          data-testid="card-assignee"
        />
      )}
      <div className="card-form-actions">
        <Button size="xs" type="submit" loading={busy} data-testid="card-form-submit">
          {action}
        </Button>
        <Button size="xs" variant="default" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** What a card moving to Blocked is waiting for: the reason, which Blocked requires, and the card it waits on if any. */
export function BlockedForm({
  cards,
  onSubmit,
  onCancel,
}: {
  /** The cards this one could wait on. */
  cards: Choice[];
  onSubmit: (reason: string, waitsOn: number | null) => Promise<void>;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [waitsOn, setWaitsOn] = useState<string | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="card-form"
      data-testid="blocked-form"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setRefused(null);
        try {
          await onSubmit(reason, waitsOn === null ? null : Number(waitsOn));
        } catch (problem) {
          setRefused((problem as Error).message);
          setBusy(false);
        }
      }}
    >
      {refused && <Refusal testid="blocked-refused">{refused}</Refusal>}
      <Textarea
        label="What is it waiting for?"
        required
        data-autofocus
        autosize
        minRows={2}
        value={reason}
        onChange={(event) => setReason(event.currentTarget.value)}
        data-testid="blocked-reason"
      />
      <Select
        label="Waits on"
        description="If it is waiting for another card, its assignee is told when that card is done."
        placeholder="No card"
        clearable
        searchable
        value={waitsOn}
        data={cards}
        onChange={setWaitsOn}
        data-testid="blocked-waits-on"
      />
      <div className="card-form-actions">
        <Button size="xs" type="submit" loading={busy} data-testid="blocked-submit">
          Move to Blocked
        </Button>
        <Button size="xs" variant="default" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** A comment to add to a card. */
export function CommentForm({ onSubmit }: { onSubmit: (text: string) => Promise<boolean> }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);
  return (
    <form
      className="card-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!text.trim()) return setTried(true);
        setBusy(true);
        if (await onSubmit(text)) {
          setText("");
          setTried(false);
        }
        setBusy(false);
      }}
    >
      <Textarea
        label="Add a comment"
        autosize
        minRows={2}
        maxRows={8}
        value={text}
        error={tried && !text.trim() ? "Write the comment first." : undefined}
        onChange={(event) => setText(event.currentTarget.value)}
        data-testid="comment-text"
      />
      <div className="card-form-actions">
        <Button size="xs" type="submit" loading={busy} data-testid="comment-send">
          Comment
        </Button>
      </div>
    </form>
  );
}
