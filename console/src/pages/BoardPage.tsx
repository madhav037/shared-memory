import { Drawer, SegmentedControl, Select, UnstyledButton } from "@mantine/core";
import { IconAlertTriangle, IconMessage, IconSettings } from "@tabler/icons-react";
import { Link, useParams, useSearchParams } from "react-router";

import {
  fetchArchive,
  fetchBoard,
  fetchCard,
  fetchMembers,
  type BoardFilters,
  type Card,
  type CardDetail,
} from "../api/client";
import { Placeholder, Refusal, Trail } from "../components/Bits";
import { Prose } from "../components/Prose";
import { COLUMN_NAMES, PRIORITY_NAMES, dueness, fileLink, today, type Priority } from "../lib/board";
import { day, folderUrl, memoryUrl, moment, plural } from "../lib/format";
import { useAsked } from "../lib/useAsked";

const FILTERS = ["assignee", "label", "priority"] as const;

/** A project's board: its cards in To do, Doing, Blocked and Done, and the archive of cards done long ago. */
export function BoardPage() {
  const { projectId = "" } = useParams();
  const [asked, setAsked] = useSearchParams();
  const filters: BoardFilters = Object.fromEntries(
    FILTERS.map((name) => [name, asked.get(name) ?? undefined]).filter(([, value]) => value),
  );
  const inArchive = asked.get("view") === "archive";
  const opened = Number(asked.get("card")) || null;
  const { answer: team } = useAsked((signal) => fetchMembers(signal), []);
  const { answer: board, refused } = useAsked((signal) => fetchBoard(projectId, filters, signal), [projectId, filters]);
  const { answer: archive, refused: archiveRefused } = useAsked(
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
  const open = (number: number | null) => change((next) => (number ? next.set("card", String(number)) : next.delete("card")));
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
        The work in {board.project_name}, from To do to Done. Members’ coding agents add, claim and move its cards; a card
        done more than 14 days ago leaves the board for the archive.
      </p>
      <div className="page-meta">
        <span>
          <b>{plural(shown, "card")}</b> on the board{narrowed ? ", as narrowed" : ""}
        </span>
        <Link to={folderUrl(home)} className="quiet-link">
          Project memory
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
      </div>

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
              className={`board-column ${one.column}`}
              aria-label={one.name}
              data-testid={`column-${one.column}`}
            >
              <h2 className="board-column-head">
                {one.name} <span className="count-figure">{one.cards.length}</span>
              </h2>
              {one.cards.length === 0 ? (
                <p className="board-empty">{narrowed ? "None match." : "Nothing here."}</p>
              ) : (
                <ol className="board-cards">
                  {one.cards.map((card) => (
                    <li key={card.number}>
                      <CardTile card={card} onOpen={() => open(card.number)} current={opened === card.number} />
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
        {opened !== null && <CardPanel projectId={projectId} number={opened} people={people} onOpen={open} />}
      </Drawer>
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

/** A card as the board shows it: enough to recognise it, the rest in its panel. */
function CardTile({ card, onOpen, current }: { card: Card; onOpen: () => void; current: boolean }) {
  return (
    <UnstyledButton
      className={current ? "card-tile current" : "card-tile"}
      onClick={onOpen}
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
          <span key={label} className="label">
            {label}
          </span>
        ))}
      </span>
    </UnstyledButton>
  );
}

/** One card whole: its fields, what it links to, why it is blocked, and what members have said on it. */
function CardPanel({
  projectId,
  number,
  people,
  onOpen,
}: {
  projectId: string;
  number: number;
  people: Map<string, string>;
  onOpen: (number: number) => void;
}) {
  const { answer: card, refused } = useAsked((signal) => fetchCard(projectId, number, signal), [projectId, number]);
  if (refused) return <Refusal testid="card-refused">{refused}</Refusal>;
  if (!card) return <Placeholder lines={8} />;
  return (
    <article className="card-panel" data-testid="card-panel">
      <h2 className="card-panel-title">{card.title}</h2>
      <dl className="card-fields">
        <dt>Column</dt>
        <dd>{COLUMN_NAMES[card.column]}</dd>
        <dt>Assignee</dt>
        <dd>{card.assignee_name ?? "No assignee"}</dd>
        <dt>Priority</dt>
        <dd>{PRIORITY_NAMES[card.priority]}</dd>
        {card.labels.length > 0 && (
          <>
            <dt>Labels</dt>
            <dd>
              {card.labels.map((label) => (
                <span key={label} className="label">
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
