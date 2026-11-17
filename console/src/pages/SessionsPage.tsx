import {
  IconArrowsCross,
  IconGitBranch,
  IconHourglass,
  IconLayoutColumns,
  IconMessage,
  IconShieldOff,
} from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";

import {
  fetchSessions,
  type ActiveSession,
  type NamedSession,
  type ProjectSessions,
  type SessionCollision,
  type SessionGate,
  type SessionMessage,
} from "../api/client";
import { Placeholder, ProjectLinks, Refusal, Trail } from "../components/Bits";
import { moment, plural } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** How often the page asks again, so a new collision, gate or message shows without reloading. */
const EVERY_MS = 4000;

/** What the page shows: the server's answer, and, per gate and earlier session, when its wait ends on this browser's clock. */
type Shown = ProjectSessions & { ends: Map<string, number> };

function waitKey(gate: SessionGate, earlier: NamedSession, until: string): string {
  return `${gate.later.member_id} ${earlier.member_id} ${until}`;
}

/**
 * A project's active sessions: whose each is, the coding agent it runs in, its branch, its activity, the files it holds
 * a lock on and the files it has touched; the project's collisions and gates, each gate's time left counting down; and
 * the signed-in member's own sessions' messages. It asks again every few seconds and changes nothing: a lock, a gate
 * and a message move only from a session.
 */
export function SessionsPage() {
  const { projectId = "" } = useParams();
  // When each gate's wait ends on this browser's clock, the earliest any answer gave, so the time left only ever counts
  // down, whatever the time each answer took to arrive.
  const ends = useRef(new Map<string, number>());
  const { answer: found, refused, reload } = useAsked(
    (signal) =>
      fetchSessions(projectId, signal).then((answer): Shown => {
        const received = Date.now() - Date.parse(answer.now);
        for (const gate of answer.gates)
          for (const wait of gate.waits_for) {
            const key = waitKey(gate, wait.earlier, wait.until);
            const at = Date.parse(wait.until) + received;
            ends.current.set(key, Math.min(at, ends.current.get(key) ?? at));
          }
        return { ...answer, ends: new Map(ends.current) };
      }),
    [projectId],
  );
  useEffect(() => {
    const asking = window.setInterval(reload, EVERY_MS);
    return () => window.clearInterval(asking);
  }, [reload]);

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
        The coding agents at work in {found.project_name} now, the files each session holds, where two are on nearly
        the same work, and your sessions’ messages. The page keeps itself up to date; a session leaves it when it ends
        or goes idle.
      </p>
      <div className="page-meta">
        <span>
          <b>{plural(found.sessions.length, "active session")}</b>
          {files > 0 ? `, holding ${plural(files, "file")}` : ""}
        </span>
        <ProjectLinks projectId={found.project_id} here="sessions" />
      </div>

      {found.gates.length > 0 && <Gates found={found} />}
      {found.collisions.length > 0 && <Collisions collisions={found.collisions} />}
      {found.messages.length > 0 && <Messages messages={found.messages} />}

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
        {session.branch && (
          <span className="session-branch" data-testid="session-branch" title="Its git branch">
            <IconGitBranch size={14} stroke={1.6} aria-hidden />
            {session.branch}
          </span>
        )}
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
        {!session.can_be_gated && (
          <span
            className="mark"
            data-testid="cannot-be-gated"
            title="Its coding agent has no hooks, so nothing refuses its edits: a gate on it is only guidance"
          >
            <IconShieldOff size={14} stroke={1.6} aria-hidden />
            Can’t be gated
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
      {session.touched_files.length > 0 && (
        <section className="session-touched" aria-label="Files it touched" data-testid="session-touched">
          <h3 className="card-section-head">Touched {plural(session.touched_files.length, "file")}, the latest first</h3>
          <ul className="card-links">
            {session.touched_files.map((path) => (
              <li key={path}>
                <span className="path">{path}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </li>
  );
}

/** This browser's clock, ticking each second, for the time left on a gate. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const ticking = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(ticking);
  }, []);
  return now;
}

/** Minutes and seconds left, as "4:05 left", or that the wait has passed. */
function left(ms: number): string {
  if (ms <= 0) return "the wait has passed";
  const seconds = Math.ceil(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} left`;
}

/** A session as a collision, a gate or a message names it: its member, and its coding agent when known. */
function Who({ session }: { session: NamedSession }) {
  return (
    <>
      <b title={session.member_id}>{session.member_name}</b>
      {session.agent ? ` (${session.agent})` : ""}
    </>
  );
}

function Activity({ session }: { session: NamedSession }) {
  return session.activity ? (
    <span className="talk-activity">“{session.activity}”</span>
  ) : (
    <span className="talk-activity none">no activity stated</span>
  );
}

/** Each gated later session, and each earlier session it waits for with the time left of the project's wait. */
function Gates({ found }: { found: Shown }) {
  const now = useNow();
  return (
    <section className="talk" aria-label="Gates" data-testid="gates">
      <h2 className="talk-head">
        <IconHourglass size={18} stroke={1.6} aria-hidden />
        {plural(found.gates.length, "gated session")}
      </h2>
      <p className="talk-lede">
        A later session’s file edits on colliding work wait until the project’s wait has passed, or its member says it
        is different work. Reading, searching and planning go ahead.
      </p>
      <ul className="talk-list">
        {found.gates.map((gate) => (
          <li key={gate.later.member_id + gate.waits_for.map((one) => one.until).join()} data-testid="gate">
            <p className="talk-line">
              <Who session={gate.later} />’s session is gated, working on <Activity session={gate.later} />.
            </p>
            <ul className="talk-waits">
              {gate.waits_for.map((wait) => {
                const end = found.ends.get(waitKey(gate, wait.earlier, wait.until)) ?? Date.parse(wait.until);
                return (
                  <li key={wait.earlier.member_id + wait.until} data-testid="gate-wait">
                    Waits for <Who session={wait.earlier} />, on <Activity session={wait.earlier} />:{" "}
                    <time className="talk-left" dateTime={wait.until} data-testid="time-left">
                      {left(end - now)}
                    </time>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Two active sessions found on nearly the same work: which is later, which earlier, and what made it. */
function Collisions({ collisions }: { collisions: SessionCollision[] }) {
  return (
    <section className="talk" aria-label="Collisions" data-testid="collisions">
      <h2 className="talk-head">
        <IconArrowsCross size={18} stroke={1.6} aria-hidden />
        {plural(collisions.length, "collision")}
      </h2>
      <ul className="talk-list">
        {collisions.map((one) => (
          <li key={`${one.later.member_id} ${one.earlier.member_id} ${one.found_at}`} data-testid="collision">
            <p className="talk-line">
              <Who session={one.later} />’s session, on <Activity session={one.later} />, is on nearly the same work as{" "}
              <Who session={one.earlier} />’s, on <Activity session={one.earlier} />.
            </p>
            <p className="talk-meta">
              Found from the later session’s {one.cause === "prompt" ? "prompt" : "activity"},{" "}
              <time dateTime={one.found_at}>{moment(one.found_at)}</time>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The messages the signed-in member's sessions sent or were sent: no one else's are ever here. */
function Messages({ messages }: { messages: SessionMessage[] }) {
  return (
    <section className="talk" aria-label="Your sessions’ messages" data-testid="messages">
      <h2 className="talk-head">
        <IconMessage size={18} stroke={1.6} aria-hidden />
        Your sessions’ messages
      </h2>
      <ul className="talk-list">
        {messages.map((one) => (
          <li key={`${one.sender_member_id} ${one.recipient_member_id} ${one.sent_at}`} data-testid="message">
            <p className="talk-meta">
              {one.sent_by_me ? (
                <>
                  You to <b title={one.recipient_member_id}>{one.recipient_name}</b>
                </>
              ) : (
                <>
                  <b title={one.sender_member_id}>{one.sender_name}</b> to you
                </>
              )}
              , <time dateTime={one.sent_at}>{moment(one.sent_at)}</time>
              {" · "}
              {one.delivered_at ? (
                <>
                  told {one.sent_by_me ? "their" : "your"} session{" "}
                  <time dateTime={one.delivered_at}>{moment(one.delivered_at)}</time>
                </>
              ) : (
                `waiting for ${one.sent_by_me ? "their" : "your"} session`
              )}
            </p>
            <p className="talk-text" data-testid="message-text">
              {one.text}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
