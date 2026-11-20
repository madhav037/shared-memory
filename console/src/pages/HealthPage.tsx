import { Link, useParams } from "react-router";

import { fetchHealth, type ProjectHealth } from "../api/client";
import { InDoubtMark, OutdatedMark, Placeholder, ProjectLinks, Refusal, Trail } from "../components/Bits";
import { doubtsUrl, REASON_NAMES } from "../lib/challenge";
import { day, memoryUrl, plural, typeName } from "../lib/format";
import { useAsked } from "../lib/useAsked";

type Outdated = ProjectHealth["possibly_outdated"][number];
type Doubted = ProjectHealth["in_doubt"][number];

/**
 * A project's health (CONTEXT.md: Project health), for its leads and the company's admins: the project memory that may
 * no longer be true, and the memory sessions doubt. It only reads: pinning, retiring and deciding stay on the memory's
 * own page and the challenges page, which each entry links to (ADR-0009).
 */
export function HealthPage() {
  const { projectId = "" } = useParams();
  const { answer: health, refused } = useAsked((signal) => fetchHealth(projectId, signal), [projectId]);

  if (refused)
    return (
      <div className="narrow">
        <Trail steps={[]} />
        <Refusal testid="health-refused">{refused}</Refusal>
      </div>
    );
  if (!health) return <Placeholder lines={10} />;

  return (
    <div className="narrow">
      <Trail steps={[{ path: `projects/${health.project_id}`, name: health.project_name }]} />
      <h1 className="page-title">Project health</h1>
      <p className="standfirst">
        What <b data-testid="project-name">{health.project_name}</b>’s project memory is doing now: what no coding agent
        has used for a long time, and what sessions doubt. Nothing here changes it.
      </p>
      <div className="page-meta">
        <ProjectLinks projectId={health.project_id} />
      </div>

      <section aria-labelledby="outdated-heading">
        <h2 className="section-heading" id="outdated-heading">
          Possibly outdated
        </h2>
        <p className="section-lede">
          No coding agent has recalled or read these for {plural(health.outdated_after_days, "day")} or more, and none is
          pinned. Check each still holds: pin what matters, retire what no longer does, from its own page.
        </p>
        <ul className="entries" data-testid="possibly-outdated">
          {health.possibly_outdated.length === 0 && <Nothing>No project memory has gone unused that long.</Nothing>}
          {health.possibly_outdated.map((memory) => (
            <OutdatedEntry key={memory.path} memory={memory} />
          ))}
        </ul>
      </section>

      <section aria-labelledby="in-doubt-heading">
        <h2 className="section-heading" id="in-doubt-heading">
          In doubt
        </h2>
        <p className="section-lede">
          Sessions doubt these, the most doubted first. Recall ranks each lower until its doubts are decided, on the
          challenges page.
        </p>
        <ul className="entries" data-testid="in-doubt">
          {health.in_doubt.length === 0 && <Nothing>No session doubts this project’s memory.</Nothing>}
          {health.in_doubt.map((memory) => (
            <DoubtedEntry key={memory.path} memory={memory} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function Nothing({ children }: { children: React.ReactNode }) {
  return (
    <li className="entry" style={{ color: "var(--ink-3)", fontSize: "0.9375rem" }} data-testid="nothing">
      {children}
    </li>
  );
}

function OutdatedEntry({ memory }: { memory: Outdated }) {
  return (
    <li className="entry" data-testid="outdated-memory">
      <Link className="entry-title" to={memoryUrl(memory.path)}>
        {memory.title}
      </Link>
      <p className="entry-summary">{memory.summary}</p>
      <div className="entry-meta">
        <OutdatedMark />
        <span data-testid="last-used">Last used {day(memory.last_used)}</span>
        <span>{typeName(memory.type)}</span>
        <span title={memory.author}>{memory.author_name}</span>
      </div>
    </li>
  );
}

function DoubtedEntry({ memory }: { memory: Doubted }) {
  const { in_doubt: doubt } = memory;
  return (
    <li className="entry" data-testid="doubted-memory">
      <Link className="entry-title" to={memoryUrl(memory.path)}>
        {memory.title}
      </Link>
      <p className="entry-summary" data-testid="doubt-line">
        {doubt.line}.
      </p>
      <div className="entry-meta">
        <InDoubtMark />
        <span data-testid="doubt-count">Doubted by {plural(doubt.count, "member")}</span>
        {doubt.reasons.map((each) => (
          <span key={each.reason} data-testid="doubt-reason">
            {REASON_NAMES[each.reason]}: {each.count}
          </span>
        ))}
        <span title={memory.author}>{memory.author_name}</span>
        <Link to={doubtsUrl(memory.path)} data-testid="see-doubts">
          See its challenges
        </Link>
      </div>
    </li>
  );
}
