import { IconAlertTriangle, IconLock, IconPin, IconScale } from "@tabler/icons-react";
import { Link } from "react-router";

import { folderUrl, levelName } from "../lib/format";

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
