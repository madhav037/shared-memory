import { IconGitBranch } from "@tabler/icons-react";
import { Link, useParams } from "react-router";

import { fetchRecentSessions, type RecentSession } from "../api/client";
import { Placeholder, ProjectLinks, Refusal, Trail } from "../components/Bits";
import { moment, plural, sessionsUrl, toldUrl } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/**
 * A member's recent sessions in a project, the most recently seen first: their own, or every one for the project's
 * leads and the team's admins, the same readers as each session's told record. Each shows its last stated activity,
 * its branch, when it ran and how many memories it was told, and opens its told record. Reading it changes nothing.
 */
export function RecentSessionsPage() {
  const { projectId = "" } = useParams();
  const { answer: found, refused } = useAsked((signal) => fetchRecentSessions(projectId, signal), [projectId]);

  if (refused)
    return (
      <div className="column">
        <Trail steps={[]} />
        <Refusal testid="recent-sessions-refused">{refused}</Refusal>
      </div>
    );
  if (!found) return <Placeholder lines={8} />;

  return (
    <div className="column" data-testid="recent-sessions-page">
      <Trail steps={[{ path: `projects/${found.project_id}`, name: found.project_name }]} />
      <h1 className="page-title">Recent sessions</h1>
      <p className="standfirst">
        The sessions of {found.project_name} from the last {plural(found.told_days, "day")} whose told record you may
        read: your own, or every one when you look after the project. Open one to read what Shared Memory told it.
      </p>
      <div className="page-meta">
        <span>
          <b>{plural(found.sessions.length, "session")}</b>
        </span>
        <Link to={sessionsUrl(found.project_id)}>Active sessions</Link>
        <ProjectLinks projectId={found.project_id} />
      </div>

      {found.sessions.length === 0 ? (
        <p className="empty" data-testid="no-recent-sessions" style={{ marginTop: 28 }}>
          No session of yours ran in {found.project_name} in the last {plural(found.told_days, "day")}.
        </p>
      ) : (
        <ol className="entries sessions" data-testid="recent-sessions">
          {found.sessions.map((one) => (
            <Recent key={one.session_number} projectId={found.project_id} session={one} />
          ))}
        </ol>
      )}
    </div>
  );
}

function At({ at }: { at: string }) {
  return <time dateTime={at}>{moment(at)}</time>;
}

/** One recent session: who and where, its last stated activity, when it ran, and how many memories it was told. */
function Recent({ projectId, session }: { projectId: string; session: RecentSession }) {
  return (
    <li className="entry session" data-testid="recent-session">
      <div className="session-who">
        <span className="session-member" title={session.member_id}>
          {session.member_name}
        </span>
        <span>{session.agent ?? "Coding agent not yet known"}</span>
        {session.repository && <span className="session-repository">{session.repository}</span>}
        {session.branch && (
          <span className="session-branch" data-testid="recent-session-branch" title="Its git branch">
            <IconGitBranch size={14} stroke={1.6} aria-hidden />
            {session.branch}
          </span>
        )}
      </div>
      {session.activity ? (
        <p className="session-activity" data-testid="recent-session-activity">
          {session.activity}
        </p>
      ) : (
        <p className="session-activity none" data-testid="recent-session-activity">
          No activity stated.
        </p>
      )}
      <div className="entry-meta">
        <span data-testid="recent-session-state">{session.active ? "Active" : "Ended or idle"}</span>
        <span>
          Started <At at={session.started_at} />
        </span>
        <span>
          Last call <At at={session.last_seen_at} />
        </span>
        <span data-testid="recent-session-told">Told {plural(session.memories_told, "memory", "memories")}</span>
        <Link to={toldUrl(projectId, session.session_number)} data-testid="to-told">
          What it was told
        </Link>
      </div>
    </li>
  );
}
