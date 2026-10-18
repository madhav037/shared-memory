import {
  IconAlertTriangle,
  IconClock,
  IconFolder,
  IconLayoutColumns,
  IconLock,
  IconPin,
  IconScale,
  IconSettings,
  IconTerminal2,
} from "@tabler/icons-react";
import { Children, type ReactNode } from "react";
import { Link } from "react-router";

import { boardUrl } from "../lib/board";
import { folderUrl, levelName, sessionsUrl } from "../lib/format";

const STROKE = 1.6;

/** A refusal from the server, in its own words. */
export function Refusal({ children, testid }: { children: React.ReactNode; testid?: string }) {
  return (
    <div className="refusal" role="alert" data-testid={testid}>
      <IconAlertTriangle size={16} stroke={STROKE} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/** The shape of what is coming. */
export function Placeholder({ lines = 6 }: { lines?: number }) {
  return (
    <div className="placeholder" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, line) => (
        <span key={line} />
      ))}
    </div>
  );
}

/** Where a folder or memory sits: every folder on the way down, each one a link. */
export function Trail({ steps }: { steps: { path: string; name: string }[] }) {
  return (
    <nav aria-label="Where this is">
      <ol className="trail">
        <li>
          <Link to="/">Contents</Link>
        </li>
        {steps.map((step) => (
          <li key={step.path}>
            <Link to={folderUrl(step.path)}>{step.name}</Link>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** The pages every project has, the one in front of you named rather than linked. */
const PROJECT_PAGES = [
  { page: "memory", name: "Memory", Icon: IconFolder },
  { page: "board", name: "Board", Icon: IconLayoutColumns },
  { page: "sessions", name: "Sessions", Icon: IconTerminal2 },
  { page: "settings", name: "Settings", Icon: IconSettings },
] as const;

type ProjectPage = (typeof PROJECT_PAGES)[number]["page"];

function projectPageUrl(projectId: string, page: ProjectPage): string {
  if (page === "memory") return folderUrl(`projects/${projectId}`);
  if (page === "board") return boardUrl(projectId);
  if (page === "sessions") return sessionsUrl(projectId);
  return `/projects/${encodeURIComponent(projectId)}/settings`;
}

/** One project's pages, the same four links on each of them. */
export function ProjectLinks({ projectId, here }: { projectId: string; here: ProjectPage }) {
  return (
    <nav className="project-links" aria-label="This project’s pages">
      {PROJECT_PAGES.map(({ page, name, Icon }) =>
        page === here ? (
          <span key={page} className="project-link-here" aria-current="page">
            <Icon size={14} stroke={STROKE} aria-hidden />
            {name}
          </span>
        ) : (
          <Link key={page} to={projectPageUrl(projectId, page)} className="quiet-link" data-testid={`to-${page}`}>
            <Icon size={14} stroke={STROKE} aria-hidden />
            {name}
          </Link>
        ),
      )}
    </nav>
  );
}

/**
 * A meta line whose parts are separated by a middle dot, as in "First written 2 Jun 2026 · 4 versions". Each dot
 * travels with the part after it and sits in a margin the line clips off, so a dot that a wrap carries to the start of
 * a line is out of sight: no line opens or ends on one, and parts left out leave no stray dot.
 */
export function Dotted({
  className,
  testid,
  hidden = false,
  children,
}: {
  className: string;
  testid?: string;
  /** For a line that only repeats what is said elsewhere on the page. */
  hidden?: boolean;
  children: ReactNode;
}) {
  const parts = Children.toArray(children);
  return (
    <div className={`dotted ${className}`} data-testid={testid} aria-hidden={hidden || undefined}>
      {parts.map((part, place) => (
        <span className="dotted-part" key={place}>
          {place > 0 && (
            <span className="dot" aria-hidden>
              ·
            </span>
          )}
          {part}
        </span>
      ))}
    </div>
  );
}

/** How much weight a memory carries, set by type rank rather than colour. */
export function Rank({ level }: { level: string }) {
  return <span className={level === "personal" ? "rank personal" : "rank"}>{levelName(level)}</span>;
}

export function PinnedMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="mark strong" title="Pinned into every briefing">
      <IconPin size={14} stroke={STROKE} aria-hidden />
      {compact ? <span className="visually-hidden">Pinned</span> : "Pinned"}
    </span>
  );
}

export function ChallengedMark({ count = 1, compact = false }: { count?: number; compact?: boolean }) {
  const words = count > 1 ? `${count} challenges` : "Challenged";
  return (
    <span className="mark alert" title={words}>
      <IconScale size={14} stroke={STROKE} aria-hidden />
      {compact ? <span className="visually-hidden">{words}</span> : words}
    </span>
  );
}

/** No coding agent has recalled or read it for a long time: it may no longer be true. Only a label. */
export function OutdatedMark({ compact = false }: { compact?: boolean }) {
  const words = "Possibly outdated";
  return (
    <span className="mark" title="No coding agent has recalled or read it for a long time" data-testid="outdated-mark">
      <IconClock size={14} stroke={STROKE} aria-hidden />
      {compact ? <span className="visually-hidden">{words}</span> : words}
    </span>
  );
}

export function RestrictedMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="mark" title="Restricted to its access list">
      <IconLock size={14} stroke={STROKE} aria-hidden />
      {compact ? <span className="visually-hidden">Restricted</span> : "Restricted"}
    </span>
  );
}

/** Superseded and retired memory keeps its place, visibly cancelled. */
export function StatusMark({ status }: { status: string }) {
  if (status === "superseded")
    return (
      <span className="mark">
        <span className="dagger" aria-hidden>
          †
        </span>
        Superseded
      </span>
    );
  if (status === "retired") return <span className="mark">Retired</span>;
  return null;
}

export function WaitingMark() {
  return (
    <span className="mark" title="Offered in place of another memory; waiting for its author">
      <IconScale size={14} stroke={STROKE} aria-hidden />
      Waiting on a challenge
    </span>
  );
}
