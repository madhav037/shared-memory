import { IconBook2, IconPencil, IconSparkles } from "@tabler/icons-react";
import { Link, useParams } from "react-router";

import { fetchTold, type ToldEntry } from "../api/client";
import { Placeholder, ProjectLinks, Refusal, Trail } from "../components/Bits";
import { memoryUrl, moment, plural, sessionsUrl } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/**
 * A session's told record (CONTEXT.md: Told record), for its own member, its project's leads and the team's admins:
 * its briefing as delivered, each memory recall added and each memory the before-edit hook added for a file it edited,
 * oldest first, each with when and the memory repository's commit then. It never holds what the member typed, and reading it changes nothing.
 */
export function ToldPage() {
  const { projectId = "", sessionNumber = "" } = useParams();
  const { answer: found, refused } = useAsked(
    (signal) => fetchTold(projectId, sessionNumber, signal),
    [projectId, sessionNumber],
  );

  if (refused)
    return (
      <div className="column">
        <Trail steps={[]} />
        <Refusal testid="told-refused">{refused}</Refusal>
      </div>
    );
  if (!found) return <Placeholder lines={8} />;

  return (
    <div className="column" data-testid="told-page">
      <Trail steps={[{ path: `projects/${found.project_id}`, name: found.project_name }]} />
      <h1 className="page-title">What it was told</h1>
      <p className="standfirst">
        Everything Shared Memory told <b data-testid="told-member">{found.member_name}</b>’s session
        {found.repository ? ` in ${found.repository}` : ""}, in order: its briefing, every memory recall added to a
        prompt and every memory added before it edited a file the memory is tied to. What they typed is never kept. Each is kept for {plural(found.told_days, "day")}.
      </p>
      <div className="page-meta">
        <span>{found.agent ?? "Coding agent not yet known"}</span>
        <span>
          Started <time dateTime={found.started_at}>{moment(found.started_at)}</time>
        </span>
        <Link to={sessionsUrl(found.project_id)}>Sessions</Link>
        <ProjectLinks projectId={found.project_id} />
      </div>

      {found.told.length === 0 ? (
        <p className="empty" data-testid="told-nothing" style={{ marginTop: 28 }}>
          Nothing told to this session is kept: it was told nothing in the last {plural(found.told_days, "day")}.
        </p>
      ) : (
        <ol className="entries told" data-testid="told">
          {found.told.map((one, place) => (
            <Told key={place} told={one} />
          ))}
        </ol>
      )}
    </div>
  );
}

function Told({ told }: { told: ToldEntry }) {
  const when = (
    <span>
      <time dateTime={told.at}>{moment(told.at)}</time>
    </span>
  );
  const commit = told.commit && (
    <span className="path" title={`The memory repository's commit then: ${told.commit}`}>
      @{told.commit.slice(0, 7)}
    </span>
  );
  if (told.kind === "briefing")
    return (
      <li className="entry" data-testid="told-briefing">
        <div className="entry-meta">
          <span className="mark">
            <IconBook2 size={14} stroke={1.6} aria-hidden />
            Briefing
          </span>
          {when}
          {commit}
        </div>
        <pre className="told-briefing">{told.briefing}</pre>
      </li>
    );
  const memory = told.memory!;
  const beforeEdit = told.kind === "before_edit";
  return (
    <li className="entry" data-testid={beforeEdit ? "told-before-edit" : "told-recall"}>
      <div className="entry-meta">
        <span className="mark">
          {beforeEdit ? (
            <IconPencil size={14} stroke={1.6} aria-hidden />
          ) : (
            <IconSparkles size={14} stroke={1.6} aria-hidden />
          )}
          {beforeEdit ? "Before an edit" : "Recall"}
        </span>
        {beforeEdit && told.file && (
          <span className="path" data-testid="told-file">
            {told.file}
          </span>
        )}
        {when}
        {commit}
      </div>
      <Link className="entry-title" to={memoryUrl(memory.path)}>
        {memory.title}
      </Link>
      {memory.section !== memory.title && <p className="entry-summary">{memory.section}</p>}
      <p className="entry-summary path">{memory.path}</p>
    </li>
  );
}
