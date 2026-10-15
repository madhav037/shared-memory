import { Button, Drawer, Modal, SegmentedControl, Select } from "@mantine/core";
import {
  IconAlertTriangle,
  IconMessage,
  IconPencil,
  IconPlus,
  IconSettings,
  IconTerminal2,
  IconTrash,
} from "@tabler/icons-react";
import { useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import {
  addCard,
  claimCard,
  commentCard,
  deleteCard,
  editCard,
  fetchArchive,
  fetchBoard,
  fetchCard,
  fetchMembers,
  moveCard,
  type BoardColumn,
  type BoardFilters,
  type Card,
  type CardDetail,
} from "../api/client";
import { Placeholder, Refusal, Trail } from "../components/Bits";
import { BlockedForm, CardForm, CommentForm } from "../components/CardEdits";
import { Prose } from "../components/Prose";
import {
  PRIORITY_NAMES,
  cardEdits,
  draftOf,
  dropPlace,
  dueness,
  fileLink,
  fixedWords,
  today,
  type Column,
  type Priority,
} from "../lib/board";
import { day, folderUrl, memoryUrl, moment, plural, sessionsUrl } from "../lib/format";
import { useAsked } from "../lib/useAsked";

const FILTERS = ["assignee", "label", "priority"] as const;

/** Moving a card: to a column, at a position in it, or to its bottom without one. */
type Move = (card: Pick<Card, "number" | "column">, column: Column, position?: number) => void;

/** A change to the board, tried: what it answered, or nothing when it was refused, which the page then says. */
type Attempt = <T>(change: () => Promise<T>) => Promise<T | undefined>;

/**
 * The card a drop at this point goes above, or `null` for the bottom of the column: above the card under the pointer
 * when it is over that card's upper half, above the next one otherwise.
 */
function aimed(event: DragEvent<HTMLElement>, cards: Card[]): Card | null {
  const tile = (event.target as HTMLElement).closest<HTMLElement>("[data-card]");
  if (!tile) return null;
  const at = cards.findIndex((one) => one.number === Number(tile.dataset.card));
  if (at < 0) return null;
  const box = tile.getBoundingClientRect();
  return (event.clientY < box.top + box.height / 2 ? cards[at] : cards[at + 1]) ?? null;
}

/**
 * A project's board: its cards in To do, Doing, Blocked and Done, and the archive of cards done long ago. Members move
 * cards by dragging them, add them, and change them from a card's panel; every change goes through the board's own
 * rules on the server, and one it refuses is shown in its words.
 */
export function BoardPage() {
  const { projectId = "" } = useParams();
  const [asked, setAsked] = useSearchParams();
  const filters: BoardFilters = Object.fromEntries(
    FILTERS.map((name) => [name, asked.get(name) ?? undefined]).filter(([, value]) => value),
  );
  const inArchive = asked.get("view") === "archive";
  const opened = Number(asked.get("card")) || null;
  const { answer: team } = useAsked((signal) => fetchMembers(signal), []);
  const {
    answer: board,
    refused,
    reload,
  } = useAsked((signal) => fetchBoard(projectId, filters, signal), [projectId, filters]);
  const {
    answer: archive,
    refused: archiveRefused,
    reload: reloadArchive,
  } = useAsked(
    (signal) => (inArchive ? fetchArchive(projectId, filters, signal) : Promise.resolve(null)),
    [projectId, filters, inArchive],
  );

  const change = (update: (next: URLSearchParams) => void) =>
    setAsked((was) => {
      const next = new URLSearchParams(was);
      update(next);
      return next;
    });
  const filter = (name: (typeof FILTERS)[number], value: string | null) =>
    change((next) => (value ? next.set(name, value) : next.delete(name)));
  const open = (number: number | null) => {
    setRefusal(null);
    change((next) => (number ? next.set("card", String(number)) : next.delete("card")));
  };

  // What the last change came to: why it was refused, or what it did beyond the card itself.
  const [refusal, setRefusal] = useState<string | null>(null);
  const [told, setTold] = useState<string[]>([]);
  // Counts the changes made, so an open card's panel reads its card again after each.
  const [changes, setChanges] = useState(0);
  const [adding, setAdding] = useState(false);
  const [blocking, setBlocking] = useState<{ number: number; position?: number } | null>(null);
  const [dragged, setDragged] = useState<Card | null>(null);
  const [aim, setAim] = useState<{ column: Column; before: number | null } | null>(null);

  const changed = () => {
    setChanges((count) => count + 1);
    reload();
    reloadArchive();
  };
  const attempt: Attempt = async (make) => {
    setRefusal(null);
    setTold([]);
    try {
      const done = await make();
      changed();
      return done;
    } catch (problem) {
      setRefusal((problem as Error).message);
      return undefined;
    }
  };
  const move: Move = (card, column, position) => {
    if (column === "blocked" && card.column !== "blocked") {
      // Blocked takes a reason, so the card waits where it is until the member has given one.
      setRefusal(null);
      setBlocking({ number: card.number, position });
      return;
    }
    void attempt(() => moveCard(projectId, card.number, { column, position })).then(
      (moved) => moved && setTold(fixedWords(moved)),
    );
  };
  const drop = (event: DragEvent<HTMLElement>, column: Column, cards: Card[]) => {
    event.preventDefault();
    const card = dragged;
    setDragged(null);
    setAim(null);
    if (!card) return;
    const last = cards.at(-1)?.number === card.number;
    const position = dropPlace(card, column, aimed(event, cards), last);
    if (position !== null) move(card, column, position);
  };
  const said: ReactNode = (
    <>
      {refusal && <Refusal testid="change-refused">{refusal}</Refusal>}
      {told.length > 0 && (
        <div className="board-told" role="status" data-testid="board-told">
          {told.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}
    </>
  );
  const narrowed = FILTERS.some((name) => asked.get(name));
  const people = new Map((team?.members ?? []).map((one) => [one.member_id, one.name]));

  if (refused)
    return (
      <div className="narrow">
        <Trail steps={[]} />
        <Refusal testid="board-refused">{refused}</Refusal>
      </div>
    );
  if (!board) return <Placeholder lines={10} />;

  const home = `projects/${board.project_id}`;
  const shown = board.columns.reduce((count, one) => count + one.cards.length, 0);

  return (
    <div className="board-page">
      <Trail steps={[{ path: home, name: board.project_name }]} />
      <h1 className="page-title wide">Board</h1>
      <p className="standfirst">
        The work in {board.project_name}, from To do to Done. Members and their coding agents add, claim and move its
        cards: drag one to move it, or open it to change it. A card done more than 14 days ago leaves the board for the
        archive.
      </p>
      <div className="page-meta">
        <span>
          <b>{plural(shown, "card")}</b> on the board{narrowed ? ", as narrowed" : ""}
        </span>
        <Link to={folderUrl(home)} className="quiet-link">
          Project memory
        </Link>
        <Link to={sessionsUrl(board.project_id)} className="quiet-link">
          <IconTerminal2 size={14} stroke={1.6} aria-hidden />
          Sessions
        </Link>
        <Link to={`/projects/${encodeURIComponent(board.project_id)}/settings`} className="quiet-link">
          <IconSettings size={14} stroke={1.6} aria-hidden />
          Project settings
        </Link>
      </div>

      <div className="form-line board-filters">
        <SegmentedControl
          aria-label="Board or archive"
          data-testid="board-view"
          value={inArchive ? "archive" : "board"}
          onChange={(value) => change((next) => (value === "archive" ? next.set("view", "archive") : next.delete("view")))}
          data={[
            { value: "board", label: "Board" },
            { value: "archive", label: "Archive" },
          ]}
          style={{ flex: "0 0 auto", alignSelf: "flex-end" }}
        />
        <Select
          label="Assignee"
          placeholder="Anyone"
          clearable
          searchable
          value={asked.get("assignee")}
          data={(team?.members ?? []).map((one) => ({ value: one.member_id, label: one.name }))}
          onChange={(value) => filter("assignee", value)}
          data-testid="filter-assignee"
          style={{ flex: "2 1 180px" }}
        />
        <Select
          label="Label"
          placeholder="Any label"
          clearable
          searchable
          value={asked.get("label")}
          data={board.labels}
          onChange={(value) => filter("label", value)}
          data-testid="filter-label"
          style={{ flex: "2 1 160px" }}
        />
        <Select
          label="Priority"
          placeholder="Any priority"
          clearable
          value={asked.get("priority")}
          data={Object.entries(PRIORITY_NAMES).map(([value, label]) => ({ value, label }))}
          onChange={(value) => filter("priority", value)}
          data-testid="filter-priority"
          style={{ flex: "1 1 140px" }}
        />
        {narrowed && (
          <button
            type="button"
            className="quiet-link"
            style={{ alignSelf: "flex-end", paddingBottom: 8 }}
            onClick={() => change((next) => FILTERS.forEach((name) => next.delete(name)))}
            data-testid="clear-filters"
          >
            Clear filters
          </button>
        )}
        <Button
          size="sm"
          leftSection={<IconPlus size={15} stroke={1.8} />}
          onClick={() => setAdding(true)}
          data-testid="add-card"
          style={{ flex: "0 0 auto", alignSelf: "flex-end", marginLeft: "auto" }}
        >
          Add card
        </Button>
      </div>

      {opened === null && said}

      {inArchive ? (
        <section aria-label="Archive" data-testid="archive" style={{ marginTop: 28 }}>
          {archiveRefused && <Refusal>{archiveRefused}</Refusal>}
          {!archiveRefused && !archive && <Placeholder lines={6} />}
          {archive?.cards.length === 0 && (
            <p className="empty">
              {narrowed ? "No archived card matches those filters." : "Nothing has been done long enough ago to be archived yet."}
            </p>
          )}
          {archive && archive.cards.length > 0 && (
            <div className="scroll-x">
              <table className="register">
                <thead>
                  <tr>
                    <th scope="col">Card</th>
                    <th scope="col">Title</th>
                    <th scope="col">Assignee</th>
                    <th scope="col">Labels</th>
                    <th scope="col">Done</th>
                  </tr>
                </thead>
                <tbody>
                  {archive.cards.map((card) => (
                    <tr key={card.number}>
                      <td className="card-number">{card.number}</td>
                      <td className="primary">
                        <button type="button" className="register-open" onClick={() => open(card.number)}>
                          {card.title}
                        </button>
                      </td>
                      <td>{card.assignee_name ?? "No assignee"}</td>
                      <td>{card.labels.join(", ")}</td>
                      <td style={{ whiteSpace: "nowrap" }}>{day(card.moved_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : (
        <div className="board" data-testid="board">
          {board.columns.map((one) => (
            <section
              key={one.column}
              className={`board-column ${one.column}${aim?.column === one.column ? " aimed" : ""}`}
              aria-label={one.name}
              data-testid={`column-${one.column}`}
              onDragOver={(event) => {
                if (!dragged) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                const before = aimed(event, one.cards)?.number ?? null;
                if (aim?.column !== one.column || aim.before !== before) setAim({ column: one.column, before });
              }}
              onDrop={(event) => drop(event, one.column, one.cards)}
            >
              <h2 className="board-column-head">
                {one.name} <span className="count-figure">{one.cards.length}</span>
              </h2>
              {one.cards.length === 0 ? (
                <p className="board-empty">{narrowed ? "None match." : "Nothing here."}</p>
              ) : (
                <ol className={aim?.column === one.column && aim.before === null ? "board-cards drop-last" : "board-cards"}>
                  {one.cards.map((card) => (
                    <li
                      key={card.number}
                      className={aim?.column === one.column && aim.before === card.number ? "drop-above" : undefined}
                    >
                      <CardTile
                        card={card}
                        onOpen={() => open(card.number)}
                        current={opened === card.number}
                        lifted={dragged?.number === card.number}
                        onLift={(lifted) => {
                          setDragged(lifted ? card : null);
                          if (!lifted) setAim(null);
                        }}
                      />
                    </li>
                  ))}
                </ol>
              )}
            </section>
          ))}
        </div>
      )}

      <Drawer
        opened={opened !== null}
        onClose={() => open(null)}
        position="right"
        size="min(520px, 100%)"
        title={opened !== null ? `Card ${opened}` : ""}
        styles={{ title: { fontWeight: 700, fontFamily: "var(--mono)" } }}
      >
        {opened !== null && (
          <CardPanel
            projectId={projectId}
            number={opened}
            people={people}
            labels={board.labels}
            columns={board.columns}
            changes={changes}
            said={said}
            attempt={attempt}
            move={move}
            onOpen={open}
          />
        )}
      </Drawer>

      <Modal opened={adding} onClose={() => setAdding(false)} title="Add a card" size="lg">
        <p className="margin-help" style={{ marginBottom: 14 }}>
          It goes to the bottom of To do, numbered next in {board.project_name}.
        </p>
        <CardForm
          initial={draftOf()}
          labels={board.labels}
          action="Add card"
          onCancel={() => setAdding(false)}
          onSubmit={async (draft) => {
            await addCard(projectId, {
              title: draft.title,
              description: draft.description,
              priority: draft.priority,
              labels: draft.labels,
              due_date: draft.due_date || null,
              memories: draft.memories,
              files: draft.files,
            });
            setAdding(false);
            setRefusal(null);
            setTold([]);
            changed();
          }}
        />
      </Modal>

      <Modal
        opened={blocking !== null}
        onClose={() => setBlocking(null)}
        title={blocking ? `Move card ${blocking.number} to Blocked` : ""}
      >
        {blocking && (
          <BlockedForm
            cards={board.columns
              .filter((one) => one.column !== "done")
              .flatMap((one) => one.cards)
              .filter((card) => card.number !== blocking.number)
              .map((card) => ({ value: String(card.number), label: `Card ${card.number}: ${card.title}` }))}
            onCancel={() => setBlocking(null)}
            onSubmit={async (reason, waitsOn) => {
              await moveCard(projectId, blocking.number, {
                column: "blocked",
                position: blocking.position,
                blocked_reason: reason,
                waits_on: waitsOn,
              });
              setBlocking(null);
              setTold([]);
              changed();
            }}
          />
        )}
      </Modal>
    </div>
  );
}

function PriorityMark({ priority }: { priority: Priority }) {
  if (priority === "normal") return null;
  return <span className={`priority ${priority}`}>{PRIORITY_NAMES[priority]}</span>;
}

function Due({ date }: { date: string | null }) {
  if (!date) return null;
  const state = dueness(date, today());
  const words = state === "overdue" ? "Overdue" : state === "today" ? "Due today" : "Due";
  return (
    <span className={state ? "due alert" : "due"}>
      {state === "overdue" && <IconAlertTriangle size={13} stroke={1.8} aria-hidden />}
      {words} {day(date)}
    </span>
  );
}

/**
 * A card as the board shows it: enough to recognise it, the rest in its panel. It opens like a button and is dragged
 * like a slip of paper; a member without a pointer moves it from its panel instead.
 */
function CardTile({
  card,
  onOpen,
  current,
  lifted,
  onLift,
}: {
  card: Card;
  onOpen: () => void;
  current: boolean;
  lifted: boolean;
  onLift: (lifted: boolean) => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={`card-tile${current ? " current" : ""}${lifted ? " lifted" : ""}`}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onOpen();
      }}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", `Card ${card.number}: ${card.title}`);
        onLift(true);
      }}
      onDragEnd={() => onLift(false)}
      data-card={card.number}
      data-testid="card"
      aria-label={`Card ${card.number}: ${card.title}`}
    >
      <span className="card-tile-top">
        <span className="card-number">{card.number}</span>
        <PriorityMark priority={card.priority} />
      </span>
      <span className="card-tile-title">{card.title}</span>
      {card.column === "blocked" && card.blocked_reason && (
        <span className="card-tile-reason">
          {card.blocked_reason}
          {card.waits_on !== null && ` Waits on card ${card.waits_on}.`}
        </span>
      )}
      <span className="card-tile-meta">
        {card.assignee_name && <span>{card.assignee_name}</span>}
        {card.column !== "done" && <Due date={card.due_date} />}
        {card.comments.length > 0 && (
          <span aria-label={plural(card.comments.length, "comment")}>
            <IconMessage size={13} stroke={1.6} aria-hidden /> {card.comments.length}
          </span>
        )}
        {card.labels.map((label) => (
          <span key={label} className="card-label">
            {label}
          </span>
        ))}
      </span>
    </div>
  );
}

/**
 * One card whole: its fields, what it links to, why it is blocked, and what members have said on it; and from here a
 * member claims it, moves it, edits it, comments on it and deletes it.
 */
function CardPanel({
  projectId,
  number,
  people,
  labels,
  columns,
  changes,
  said,
  attempt,
  move,
  onOpen,
}: {
  projectId: string;
  number: number;
  people: Map<string, string>;
  labels: string[];
  /** The board's columns, as the server names them. */
  columns: Pick<BoardColumn, "column" | "name">[];
  changes: number;
  said: ReactNode;
  attempt: Attempt;
  move: Move;
  onOpen: (number: number | null) => void;
}) {
  const {
    answer: card,
    refused,
    reload,
  } = useAsked((signal) => fetchCard(projectId, number, signal), [projectId, number]);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const seen = useRef(changes);
  useEffect(() => {
    if (seen.current === changes) return;
    seen.current = changes;
    reload();
  }, [changes, reload]);
  useEffect(() => {
    setEditing(false);
    setDeleting(false);
  }, [number]);

  if (refused)
    return (
      <>
        {said}
        <Refusal testid="card-refused">{refused}</Refusal>
      </>
    );
  if (!card) return <Placeholder lines={8} />;
  if (editing)
    return (
      <article className="card-panel" data-testid="card-panel">
        <CardForm
          initial={draftOf(card)}
          labels={labels}
          assignees={[...people].map(([value, label]) => ({ value, label }))}
          action="Save card"
          onCancel={() => setEditing(false)}
          onSubmit={async (draft) => {
            const fields = cardEdits(card, draft);
            // The form itself says why when this is refused, so what was typed stays in place.
            const edited = Object.keys(fields).length > 0 ? await editCard(projectId, number, fields) : null;
            if (edited) await attempt(() => Promise.resolve(edited));
            setEditing(false);
          }}
        />
      </article>
    );
  return (
    <article className="card-panel" data-testid="card-panel">
      {said}
      <h2 className="card-panel-title">{card.title}</h2>
      <div className="card-actions">
        {card.column === "to_do" && card.assignee === null && (
          <Button size="xs" onClick={() => void attempt(() => claimCard(projectId, number))} data-testid="claim-card">
            Claim
          </Button>
        )}
        <Button
          size="xs"
          variant="default"
          leftSection={<IconPencil size={14} stroke={1.6} />}
          onClick={() => setEditing(true)}
          data-testid="edit-card"
        >
          Edit
        </Button>
        {!deleting && (
          <button type="button" className="quiet-link danger" onClick={() => setDeleting(true)} data-testid="delete-card">
            <IconTrash size={14} stroke={1.6} aria-hidden />
            Delete…
          </button>
        )}
      </div>
      {deleting && (
        <div className="card-confirm">
          <p className="margin-help">
            Delete card {number} for good, with its comments? Finished work goes to Done instead.
          </p>
          <div className="card-form-actions">
            <Button
              size="xs"
              color="red"
              onClick={async () => {
                setDeleting(false);
                if (await attempt(() => deleteCard(projectId, number))) onOpen(null);
              }}
              data-testid="delete-confirm"
            >
              Delete card
            </Button>
            <Button size="xs" variant="default" onClick={() => setDeleting(false)}>
              Keep it
            </Button>
          </div>
        </div>
      )}
      <dl className="card-fields">
        <dt>Column</dt>
        <dd className="card-column">
          {columns.find((one) => one.column === card.column)?.name}
          <Select
            aria-label="Move to another column"
            placeholder="Move to…"
            size="xs"
            value={null}
            data={columns
              .filter((one) => one.column !== card.column)
              .map((one) => ({ value: one.column, label: one.name }))}
            onChange={(value) => value && move(card, value as Column)}
            data-testid="move-card"
            style={{ width: 130 }}
          />
        </dd>
        <dt>Assignee</dt>
        <dd>{card.assignee_name ?? "No assignee"}</dd>
        <dt>Priority</dt>
        <dd>{PRIORITY_NAMES[card.priority]}</dd>
        {card.labels.length > 0 && (
          <>
            <dt>Labels</dt>
            <dd>
              {card.labels.map((label) => (
                <span key={label} className="card-label">
                  {label}
                </span>
              ))}
            </dd>
          </>
        )}
        {card.due_date && (
          <>
            <dt>Due</dt>
            <dd>
              <Due date={card.due_date} />
            </dd>
          </>
        )}
        <dt>Added</dt>
        <dd>
          By {card.creator_name}, {day(card.created_at)}
        </dd>
      </dl>

      {card.column === "blocked" && card.blocked_reason && (
        <section className="card-blocked" aria-label="Why it is blocked">
          <h3 className="card-section-head">Blocked</h3>
          <p>{card.blocked_reason}</p>
          {card.waits_on !== null && (
            <p>
              Waits on{" "}
              <button type="button" className="quiet-link inline" onClick={() => onOpen(card.waits_on!)} data-testid="waits-on">
                card {card.waits_on}
              </button>
              .
            </p>
          )}
        </section>
      )}

      {card.description && (
        <section aria-label="Description">
          <Prose>{card.description}</Prose>
        </section>
      )}

      <Links card={card} />

      <section aria-label="Comments" data-testid="card-comments">
        <h3 className="card-section-head">{card.comments.length ? plural(card.comments.length, "comment") : "Comments"}</h3>
        {card.comments.length === 0 ? (
          <p className="empty">No one has commented on this card.</p>
        ) : (
          <ol className="card-comments">
            {card.comments.map((comment, place) => (
              <li key={place}>
                <div className="card-comment-by">
                  <b title={comment.author}>{people.get(comment.author) ?? comment.author_name}</b>{" "}
                  <span>{moment(comment.created_at)}</span>
                </div>
                <p>{comment.text}</p>
              </li>
            ))}
          </ol>
        )}
        <CommentForm onSubmit={async (text) => (await attempt(() => commentCard(projectId, number, text))) !== undefined} />
      </section>
    </article>
  );
}

function Links({ card }: { card: CardDetail }) {
  const named = (path: string) => card.titles[path] ?? path.split("/").pop();
  return (
    <>
      {card.known_issues.length > 0 && (
        <section aria-label="Known issues" data-testid="card-known-issues">
          <h3 className="card-section-head">Known issues it fixes</h3>
          <ul className="card-links">
            {card.known_issues.map((path) => (
              <li key={path}>
                <Link to={memoryUrl(path)} title={path}>
                  {named(path)}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      {card.memories.length > 0 && (
        <section aria-label="Memories" data-testid="card-memories">
          <h3 className="card-section-head">Memories</h3>
          <ul className="card-links">
            {card.memories.map((path) => (
              <li key={path}>
                <Link to={memoryUrl(path)} title={path}>
                  {named(path)}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      {card.files.length > 0 && (
        <section aria-label="Files" data-testid="card-files">
          <h3 className="card-section-head">Files</h3>
          <ul className="card-links">
            {card.files.map((entry) => {
              const file = fileLink(entry);
              return (
                <li key={entry} className="path">
                  <span className="card-repository">{file.repository}</span> {file.path}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
}
