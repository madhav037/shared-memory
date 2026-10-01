import { IconLayoutColumns, IconSettings } from "@tabler/icons-react";
import { Link, useParams } from "react-router";

import { fetchSessions, type ActiveSession } from "../api/client";
import { Placeholder, Refusal, Trail } from "../components/Bits";
import { boardUrl } from "../lib/board";
import { folderUrl, moment, plural } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/**
 * A project's active sessions: whose each is, the coding agent it runs in, its activity and the files it holds a lock
 * on. It is read as it was when the page opened, and it changes nothing: a lock moves only from a session.
 */
export function SessionsPage() {
  const { projectId = "" } = useParams();
  const { answer: found, refused } = useAsked((signal) => fetchSessions(projectId, signal), [projectId]);

  if (refused)
    return (
      <div className="column">
        <Trail steps={[]} />
        <Refusal testid="sessions-refused">{refused}</Refusal>
      </div>
    );
  if (!found) return <Placeholder lines={8} />;

  const home = `projects/${found.project_id}`;
  const files = found.sessions.reduce((count, one) => count + one.locks.length, 0);

  return (
    <div className="column" data-testid="sessions-page">
      <Trail steps={[{ path: home, name: found.project_name }]} />
      <h1 className="page-title">Sessions</h1>
      <p className="standfirst">
        The coding agents at work in {found.project_name} now: whose each session is, what it is working on and the
        files it holds. A session leaves this page when it ends or goes idle. Nothing here changes one.
      </p>
      <div className="page-meta">
        <span>
          <b>{plural(found.sessions.length, "active session")}</b>
          {files > 0 ? `, holding ${plural(files, "file")}` : ""}
        </span>
        <Link to={folderUrl(home)} className="quiet-link">
          Project memory
        </Link>
        <Link to={boardUrl(found.project_id)} className="quiet-link">
          <IconLayoutColumns size={14} stroke={1.6} aria-hidden />
          Board
        </Link>
        <Link to={`/projects/${encodeURIComponent(found.project_id)}/settings`} className="quiet-link">
          <IconSettings size={14} stroke={1.6} aria-hidden />
          Project settings
        </Link>
      </div>

      {found.sessions.length === 0 ? (
        <p className="empty" data-testid="no-sessions" style={{ marginTop: 28 }}>
          No session is active in {found.project_name} right now. One appears here when a member’s coding agent starts
          work in a repository of this project.
        </p>
      ) : (
        <ol className="entries sessions" data-testid="sessions">
          {found.sessions.map((one, place) => (
            <Session key={place} session={one} />
          ))}
        </ol>
      )}
    </div>
  );
}

function At({ at }: { at: string }) {
  return <time dateTime={at}>{moment(at)}</time>;
}

/** One active session, set out as an entry: who and where, what it is working on, when, and the files it holds. */
function Session({ session }: { session: ActiveSession }) {
  return (
    <li className="entry session" data-testid="session">
      <div className="session-who">
        <span className="session-member" title={session.member_id}>
          {session.member_name}
        </span>
        <span data-testid="session-agent">{session.agent ?? "Coding agent not yet known"}</span>
        {session.repository && <span className="session-repository">{session.repository}</span>}
      </div>
      {session.activity ? (
        <p className="session-activity" data-testid="session-activity">
          {session.activity}
        </p>
      ) : (
        <p className="session-activity none" data-testid="session-activity">
          No activity stated.
        </p>
      )}
      <div className="entry-meta">
        {session.from_card && (
          <span className="mark" data-testid="from-card" title="This session stated no activity">
            <IconLayoutColumns size={14} stroke={1.6} aria-hidden />
            From their card in Doing
          </span>
        )}
        <span>
          Started <At at={session.started_at} />
        </span>
        <span>
          Last call <At at={session.last_seen_at} />
        </span>
      </div>
      {session.locks.length > 0 && (
        <section className="session-locks" aria-label="Files it holds" data-testid="session-locks">
          <h3 className="card-section-head">Holds {plural(session.locks.length, "file")}</h3>
          <ul className="card-links">
            {session.locks.map((lock) => (
              <li key={`${lock.repository}:${lock.path}`}>
                <span className="path">
                  <span className="card-repository">{lock.repository}</span> {lock.path}
                </span>
                <span className="session-lock-times">
                  since <At at={lock.taken_at} />, last used <At at={lock.last_used_at} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </li>
  );
}
