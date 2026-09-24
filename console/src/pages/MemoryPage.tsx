import { Button, Checkbox, CopyButton, Tooltip } from "@mantine/core";
import {
  IconArchive,
  IconArrowBackUp,
  IconCheck,
  IconClockHour4,
  IconCopy,
  IconPin,
  IconPinnedOff,
  IconScale,
  IconShieldCheck,
  IconUser,
} from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { fetchMemoryAt, pinAt, retireAt, unpinAt, type MemoryDetail } from "../api/client";
import { PinnedMark, Placeholder, Rank, Refusal, StatusMark, Trail } from "../components/Bits";
import { useContents } from "../components/Contents";
import { Prose } from "../components/Prose";
import { day, memoryUrl, moment, plural, projectIn, typeName } from "../lib/format";
import { useAsked } from "../lib/useAsked";
import { inForce, whatHappened } from "../lib/versions";
import { headerChanges, HistoryLedger, ThenText, Timeline, useHistory, type History } from "./HistoryPanel";

/** One memory, set as printed text, with its standing in the margin and its history below. */
export function MemoryPage() {
  const [asked] = useSearchParams();
  const path = asked.get("path") ?? "";
  const { answer: memory, refused, reload } = useAsked((signal) => fetchMemoryAt(path, signal), [path]);
  const { folders, load } = useContents();
  const [view, setView] = useState<"text" | "source">("text");
  const history = useHistory(path);
  const text = useRef<HTMLDivElement>(null);
  const parent = path.split("/").slice(0, -1).join("/");
  const folder = folders.get(parent);

  useEffect(() => {
    if (parent && !folder) load(parent);
  }, [parent, folder, load]);

  if (refused)
    return (
      <div className="narrow">
        <Trail steps={[]} />
        <Refusal testid="memory-refused">{refused}</Refusal>
      </div>
    );
  if (!memory) return <Placeholder lines={12} />;

  const steps = folder ? [...folder.trail, { path: parent, name: folder.name }] : [];
  const cancelled = memory.status !== "active";

  return (
    <article className="reading" data-testid="memory">
      <header className="reading-head">
        <Trail steps={steps} />
        <h1 className="page-title" data-testid="memory-title">
          {memory.status === "superseded" && (
            <span className="dagger" aria-hidden>
              †{" "}
            </span>
          )}
          <span className={cancelled ? "cancelled-title" : undefined}>{memory.title}</span>
        </h1>
        <p className="standfirst summary">{memory.summary}</p>
        {history && <Currency history={history} />}
        <p className="standing-line" aria-hidden>
          <Rank level={memory.level} />
          <StatusMark status={memory.status} />
          <span>{typeName(memory.type)}</span>
          <span>by {memory.author_name}</span>
        </p>

        <Status memory={memory} history={history} />
      </header>

      <Margin memory={memory} history={history} onChanged={reload} />

      <div className="reading-text" ref={text}>
        <div className="view-switch" role="tablist" aria-label="How to read it">
          <button
            type="button"
            role="tab"
            aria-selected={view === "text"}
            onClick={() => setView("text")}
            data-testid="view-text"
          >
            Text
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "source"}
            onClick={() => setView("source")}
            data-testid="view-source"
          >
            As your agent reads it
          </button>
        </div>

        {history && <Timeline history={history} standing={memory.status} />}

        {history && !history.current ? (
          view === "text" ? (
            <ThenText history={history} />
          ) : history.now === undefined ? (
            <p className="then-text" aria-busy="true" style={{ color: "var(--ink-3)" }}>
              …
            </p>
          ) : (
            <Source text={history.now} />
          )
        ) : view === "text" ? (
          <Prose testid="memory-body">{memory.body}</Prose>
        ) : (
          <Source text={memory.source} />
        )}
      </div>

      <div className="reading-history">
        {history && (
          <HistoryLedger
            history={history}
            title={memory.title}
            standing={memory.status}
            onPick={() => text.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
          />
        )}
      </div>
    </article>
  );
}

/** When it was first written and last amended, and by whom: how current the text in front of you is. */
function Currency({ history }: { history: History }) {
  const first = history.versions[0];
  const last = history.versions[history.versions.length - 1];
  if (!first || !last) return null;
  return (
    <p className="currency" data-testid="currency">
      <span>First written {day(first.at)}</span>
      {history.versions.length > 1 && (
        <span>
          Last amended {moment(last.at)} by {last.name}
        </span>
      )}
      <a href="#history">{plural(history.versions.length, "version")}</a>
    </p>
  );
}

/**
 * The one box that says where this text stands: in force, challenged, cancelled, personal,
 * or, while an earlier version is open, the point in time it is being read at.
 */
function Status({ memory, history }: { memory: MemoryDetail; history: History | null }) {
  const { nameOf, projects } = useContents();

  if (history && !history.current && history.version) {
    const changes = history.marked ? headerChanges(history) : [];
    return (
      <div className="status past" role="status" data-testid="history-stamp">
        <IconClockHour4 size={18} stroke={1.6} aria-hidden />
        <div>
          <p>
            <b>
              As it stood: version {history.position + 1} of {history.versions.length}.
            </b>{" "}
            {whatHappened(history.version, memory.title)}. {inForce(history.versions, history.position)}.
            {changes.length > 0 && ` This version also changed ${changes.join(", ")}.`}
          </p>
          <div className="status-actions">
            <button type="button" className="quiet-link" onClick={() => history.moveTo(null)} data-testid="back-to-now">
              <IconArrowBackUp size={15} stroke={1.6} aria-hidden />
              Back to the current text
            </button>
            {history.position > 0 && (
              <Checkbox
                size="xs"
                radius={0}
                label="Mark what this version changed"
                checked={history.marked}
                onChange={(event) => history.setMarked(event.currentTarget.checked)}
              />
            )}
          </div>
        </div>
      </div>
    );
  }

  if (memory.status === "superseded")
    return (
      <div className="status cancelled">
        <span className="dagger" aria-hidden>
          †
        </span>
        <p data-testid="superseded-by">
          <b>Superseded.</b> Another memory has taken its place; this one stays for the record.{" "}
          {memory.superseded_by && (
            <>
              <Link to={memoryUrl(memory.superseded_by)}>Read what replaced it</Link>
              <span className="visually-hidden"> ({memory.superseded_by})</span>
            </>
          )}
        </p>
      </div>
    );

  if (memory.status === "retired")
    return (
      <div className="status cancelled">
        <IconArchive size={18} stroke={1.6} aria-hidden />
        <p data-testid="retired-banner">
          <b>Retired.</b> It is no longer true, so no session is briefed with it or recalls it. It stays for the record.
        </p>
      </div>
    );

  const challenged = memory.open_challenges.length > 0;
  const personal = memory.level === "personal";
  const project = projects.get(projectIn(memory.path) ?? "")?.name;
  return (
    <div className={challenged ? "status challenged" : personal ? "status personal" : "status in-force"}>
      {challenged ? (
        <IconScale size={18} stroke={1.6} aria-hidden />
      ) : personal ? (
        <IconUser size={18} stroke={1.6} aria-hidden />
      ) : (
        <IconShieldCheck size={18} stroke={1.6} aria-hidden />
      )}
      <div>
        {challenged && (
          <p data-testid="open-challenges">
            <b>{memory.open_challenges.length === 1 ? "Challenged." : `${memory.open_challenges.length} challenges.`}</b>{" "}
            {memory.open_challenges
              .map((challenge) =>
                challenge.kind === "retire"
                  ? `${nameOf(challenge.raised_by)} wants to retire it`
                  : `${nameOf(challenge.raised_by)} wants to supersede it`,
              )
              .join("; ")}
            .{" "}
            {memory.open_challenges.some((challenge) => challenge.may_decide) ? (
              <>
                Until you decide, it stands as it is. <Link to="/challenges">Compare and decide</Link>
              </>
            ) : (
              <>Until {memory.author_name} decides, it stands as it is.</>
            )}
          </p>
        )}
        {personal ? (
          <p data-testid="personal-banner">
            <b>Personal memory of {memory.author_name}.</b> The team can read it, but hasn’t accepted it: it becomes
            project or team memory only when its author promotes it from their coding agent.
          </p>
        ) : (
          !challenged && (
            <p data-testid="in-force">
              <b>In force.</b>{" "}
              {memory.level === "team"
                ? "It holds for every project: coding agents anywhere in the team recall it."
                : `It holds for everyone on ${project ?? "this project"}: their coding agents recall it.`}
              {memory.pinned && " It is pinned, so sessions start with it in their briefing."}
            </p>
          )
        )}
        {memory.pending.length > 0 && (
          <p data-testid="pending">
            <b>Waiting on a challenge.</b> Offered in place of{" "}
            {memory.pending.map((challenge, place) => (
              <span key={challenge.challenge_id}>
                {place > 0 ? ", " : ""}
                {challenge.replaces ? <Link to={memoryUrl(challenge.replaces)}>another memory</Link> : "another memory"}
              </span>
            ))}
            ; its author decides.
          </p>
        )}
      </div>
    </div>
  );
}

/** The file as it is on disk: its header, then its body. */
function Source({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const closing = lines.indexOf("---", 1);
  return (
    <pre className="source" data-testid="memory-source">
      {lines.map((line, number) => (
        <span key={number} className={number <= closing ? "header-line" : undefined}>
          {line}
          {"\n"}
        </span>
      ))}
    </pre>
  );
}

function Margin({ memory, history, onChanged }: { memory: MemoryDetail; history: History | null; onChanged: () => void }) {
  const { refresh } = useContents();
  const [refused, setRefused] = useState<string | null>(null);
  const [retiring, setRetiring] = useState(false);
  const [told, setTold] = useState<string | null>(null);
  const accepted = memory.level !== "personal";
  const active = memory.status === "active";

  const act = async (what: () => Promise<unknown>, after?: string) => {
    try {
      await what();
      setRefused(null);
      if (after) setTold(after);
      refresh();
      onChanged();
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  return (
    <aside className="margin" aria-label="About this memory" data-testid="memory-details">
      <dl>
        <dt>Standing</dt>
        <dd style={{ display: "flex", flexWrap: "wrap", gap: "4px 10px", alignItems: "center" }}>
          <Rank level={memory.level} />
          <StatusMark status={memory.status} />
          {memory.status === "active" && <span className="mark">Current</span>}
          {memory.pinned && <PinnedMark />}
        </dd>
        <dt>Type</dt>
        <dd>{typeName(memory.type)}</dd>
        <dt>Author</dt>
        <dd>
          {memory.author_name} <span style={{ color: "var(--ink-3)" }}>({memory.author})</span>
        </dd>
        {memory.promoted_by && (
          <>
            <dt>Promoted by</dt>
            <dd>{memory.promoted_by}</dd>
          </>
        )}
        {memory.replaces && (
          <>
            <dt>Replaces</dt>
            <dd>
              <Link to={memoryUrl(memory.replaces)}>the memory it superseded</Link>
            </dd>
          </>
        )}
        {memory.superseded_by && (
          <>
            <dt>Superseded by</dt>
            <dd>
              <Link to={memoryUrl(memory.superseded_by)}>the memory that replaced it</Link>
            </dd>
          </>
        )}
        {memory.exception_to && (
          <>
            <dt>Exception to</dt>
            <dd>
              <Link to={memoryUrl(memory.exception_to)}>a team memory</Link>, for this project only
            </dd>
          </>
        )}
        {memory.related_files.length > 0 && (
          <>
            <dt>Related files</dt>
            <dd>
              {memory.related_files.map((file) => (
                <div key={file} className="path">
                  {file}
                </div>
              ))}
            </dd>
          </>
        )}
        <dt>Cite as</dt>
        <dd>
          <Citation memory={memory} history={history} />
        </dd>
      </dl>

      {accepted && active && (
        <div className="margin-actions">
          {refused && <Refusal testid="pin-refused">{refused}</Refusal>}
          {told && (
            <p className="margin-help" data-testid="retired" role="status">
              {told}
            </p>
          )}
          {memory.pinned ? (
            <Button
              variant="default"
              size="xs"
              leftSection={<IconPinnedOff size={14} stroke={1.6} />}
              onClick={() => act(() => unpinAt(memory.path))}
              data-testid="unpin"
            >
              Unpin
            </Button>
          ) : (
            <Button
              variant="default"
              size="xs"
              leftSection={<IconPin size={14} stroke={1.6} />}
              onClick={() => act(() => pinAt(memory.path))}
              data-testid="pin"
            >
              Pin into every briefing
            </Button>
          )}
          {!retiring ? (
            <button type="button" className="quiet-link danger" onClick={() => setRetiring(true)} data-testid="retire">
              <IconArchive size={14} stroke={1.6} aria-hidden />
              Retire it…
            </button>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>
              <p className="margin-help">
                Retire it if it is no longer true. Sessions stop being briefed with it and recalling it. If someone else
                wrote it, they are asked to decide instead.
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                <Button
                  size="xs"
                  color="red"
                  onClick={() =>
                    act(async () => {
                      const done = await retireAt(memory.path);
                      setRetiring(false);
                      setTold(
                        done.status === "retired"
                          ? "Retired. It stays here for the record."
                          : `${memory.author_name} has been asked to retire it. Until they decide, it stands.`,
                      );
                    })
                  }
                  data-testid="retire-confirm"
                >
                  Retire it
                </Button>
                <Button size="xs" variant="default" onClick={() => setRetiring(false)}>
                  Keep it
                </Button>
              </div>
            </div>
          )}
          <p className="margin-help">Pinned memory goes into the briefing every session in this project starts with.</p>
        </div>
      )}
    </aside>
  );
}

/**
 * The memory at the version on the page, the way a pull request or an issue can point at it exactly:
 * its path, then the commit that version was made in.
 */
function Citation({ memory, history }: { memory: MemoryDetail; history: History | null }) {
  const commit = history?.version?.commit;
  const stamp = commit ? `${memory.path}@${commit.slice(0, 7)}` : memory.path;
  return (
    <span className="citation">
      <code data-testid="citation">
        {memory.path.split("/").map((part, place, parts) => (
          <span key={place}>
            {part}
            {place < parts.length - 1 && (
              <>
                /<wbr />
              </>
            )}
          </span>
        ))}
        {commit && <b>@{commit.slice(0, 7)}</b>}
      </code>
      <CopyButton value={stamp}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? "Copied" : "Copy the citation"}>
            <button type="button" className="quiet-link" onClick={copy} aria-label="Copy the citation">
              {copied ? <IconCheck size={14} stroke={1.8} /> : <IconCopy size={14} stroke={1.6} />}
            </button>
          </Tooltip>
        )}
      </CopyButton>
    </span>
  );
}
