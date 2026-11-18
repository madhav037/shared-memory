import { Button, Textarea } from "@mantine/core";
import {
  IconArrowsCross,
  IconBell,
  IconGitBranch,
  IconHourglass,
  IconLayoutColumns,
  IconMessage,
  IconNotes,
  IconShieldOff,
} from "@tabler/icons-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router";

import {
  answerGate,
  fetchSessions,
  sendMessage,
  type ActiveSession,
  type NamedSession,
  type ProjectSessions,
  type SessionCollision,
  type SessionGate,
  type SessionHandoffNote,
  type SessionMessage,
} from "../api/client";
import { Placeholder, ProjectLinks, Refusal, Trail } from "../components/Bits";
import { moment, plural, waitingFor } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** How often the page asks again, so a new collision, gate or message shows without reloading. */
const EVERY_MS = 4000;

/** What the page shows: the server's answer, and, per gate and earlier session, when its wait ends on this browser's clock. */
type Shown = ProjectSessions & { ends: Map<string, number> };

/** One wait of one gate: the two sessions, not only their members, since one member's two sessions can each be gated. */
function waitKey(gate: SessionGate, earlier: NamedSession, until: string): string {
  return `${gate.later.session_number} ${earlier.session_number} ${until}`;
}

/** Whether this browser can show alerts at all: the Notification API is missing in some browsers and webviews. */
function alertsHere(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/**
 * Show a browser alert for each message or gate for the signed-in member that arrives while the page is open, once the
 * member has allowed alerts. What the first answer already holds was there before the page opened, so it raises none.
 */
function useAlerts(found: ProjectSessions | null) {
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!found) return;
    const forMe = new Map<string, { title: string; body: string }>();
    for (const one of found.messages)
      if (!one.sent_by_me)
        forMe.set(`message ${one.message_id}`, { title: `${one.sender_name} sent you a message`, body: one.text });
    for (const gate of found.gates)
      for (const wait of gate.waits_for)
        if (wait.on_my_work && !wait.refused)
          forMe.set(`gate ${waitKey(gate, wait.earlier, wait.until)}`, {
            title: `${gate.later.member_name}’s session waits on your work`,
            body: "Agree or refuse on the Sessions page before the project’s wait passes.",
          });
    if (seen.current === null) {
      seen.current = new Set(forMe.keys());
      return;
    }
    for (const [key, alert] of forMe) {
      if (seen.current.has(key)) continue;
      seen.current.add(key);
      if (alertsHere() && Notification.permission === "granted") new Notification(alert.title, { body: alert.body, tag: key });
    }
  }, [found]);
}

/**
 * A project's active sessions: whose each is, the coding agent it runs in, its branch, its activity, the files it holds
 * a lock on and the files it has touched; the project's collisions and gates, each gate's time left counting down; and
 * the signed-in member's own sessions' messages. It asks again every few seconds. From here a member replies to a
 * message and agrees to or refuses a gate on their own session's work (ADR-0026), and is alerted when one arrives; a
 * lock and an activity move only from a session, and nothing here ever writes memory (ADR-0009).
 */
export function SessionsPage() {
  const { projectId = "" } = useParams();
  // When each gate's wait ends on this browser's clock, the earliest any answer gave, so the time left only ever counts
  // down, whatever the time each answer took to arrive.
  const ends = useRef(new Map<string, number>());
  const shown = useCallback((answer: ProjectSessions): Shown => {
    const received = Date.now() - Date.parse(answer.now);
    for (const gate of answer.gates)
      for (const wait of gate.waits_for) {
        const key = waitKey(gate, wait.earlier, wait.until);
        const at = Date.parse(wait.until) + received;
        ends.current.set(key, Math.min(at, ends.current.get(key) ?? at));
      }
    return { ...answer, ends: new Map(ends.current) };
  }, []);
  const {
    answer: found,
    refused,
    reload,
    setAnswer,
  } = useAsked((signal) => fetchSessions(projectId, signal).then(shown), [projectId]);
  useEffect(() => {
    const asking = window.setInterval(reload, EVERY_MS);
    return () => window.clearInterval(asking);
  }, [reload]);
  useAlerts(found);
  const changed = useCallback((answer: ProjectSessions) => setAnswer(shown(answer)), [setAnswer, shown]);

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
        or goes idle. Reply to a message, or agree to or refuse a gate on your work, here; your session hears it on its
        next step.
      </p>
      <div className="page-meta">
        <span>
          <b>{plural(found.sessions.length, "active session")}</b>
          {files > 0 ? `, holding ${plural(files, "file")}` : ""}
        </span>
        <ProjectLinks projectId={found.project_id} here="sessions" />
      </div>
      <AlertsChoice />

      {found.gates.length > 0 && <Gates found={found} onChanged={changed} />}
      {found.collisions.length > 0 && <Collisions collisions={found.collisions} />}
      {found.handoff_notes.length > 0 && <HandoffNotes notes={found.handoff_notes} />}
      {found.messages.length > 0 && (
        <Messages
          projectId={found.project_id}
          messages={found.messages}
          textLimit={found.text_limit}
          onChanged={changed}
        />
      )}

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
        {session.standby && (
          <span
            className="mark"
            data-testid="standby"
            title="Its coding agent stands by: it hears the answer the moment it comes, without its member typing"
          >
            <IconHourglass size={14} stroke={1.6} aria-hidden />
            {waitingFor(session.standby.awaits.map((one) => one.member_name))}
          </span>
        )}
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

/** Whether this browser shows alerts, and the way to allow them while it hasn't been asked. */
function AlertsChoice() {
  const [permission, setPermission] = useState(() => (alertsHere() ? Notification.permission : null));
  if (permission === null) return null;
  if (permission === "granted")
    return (
      <p className="talk-alerts" data-testid="alerts">
        <IconBell size={14} stroke={1.6} aria-hidden />
        This browser alerts you when a message or a gate for you arrives while the page is open.
      </p>
    );
  if (permission === "denied")
    return (
      <p className="talk-alerts" data-testid="alerts">
        This browser blocks alerts from the console; allow them in its site settings to hear of messages and gates here.
      </p>
    );
  return (
    <p className="talk-alerts" data-testid="alerts">
      <Button
        size="xs"
        variant="default"
        leftSection={<IconBell size={14} stroke={1.6} aria-hidden />}
        onClick={() => void Notification.requestPermission().then(setPermission)}
        data-testid="allow-alerts"
      >
        Alert me in this browser
      </Button>
      when a message or a gate for you arrives while the page is open.
    </p>
  );
}

/** Run one change from the page: busy while it runs, its refusal kept to show, the page anew when it answers. */
function useChange(onChanged: (answer: ProjectSessions) => void) {
  const [busy, setBusy] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const run = async (which: string, change: () => Promise<ProjectSessions>): Promise<boolean> => {
    if (busy) return false;
    setBusy(which);
    setRefusal(null);
    try {
      onChanged(await change());
      return true;
    } catch (problem) {
      setRefusal((problem as Error).message);
      return false;
    } finally {
      setBusy(null);
    }
  };
  return { busy, refusal, run };
}

/** Agree to or refuse a gate on the signed-in member's own session's work. A refusal may still turn to agree. */
function GateAnswer({
  projectId,
  gate,
  refused,
  onChanged,
}: {
  projectId: string;
  gate: SessionGate;
  refused: boolean;
  onChanged: (answer: ProjectSessions) => void;
}) {
  const { busy, refusal, run } = useChange(onChanged);
  const answer = (said: "agree" | "refuse") => run(said, () => answerGate(projectId, gate.later.member_id, said));
  return (
    <div className="talk-answer">
      <div className="card-form-actions">
        <Button
          size="xs"
          loading={busy === "agree"}
          disabled={busy !== null}
          onClick={() => void answer("agree")}
          data-testid="agree"
        >
          Agree: let them go ahead
        </Button>
        {!refused && (
          <Button
            size="xs"
            variant="default"
            loading={busy === "refuse"}
            disabled={busy !== null}
            onClick={() => void answer("refuse")}
            data-testid="refuse"
          >
            Refuse: keep them waiting
          </Button>
        )}
      </div>
      {refusal && <Refusal testid="answer-refused">{refusal}</Refusal>}
    </div>
  );
}

/** Each gated later session, and each earlier session it waits for with the time left of the project's wait. */
function Gates({ found, onChanged }: { found: Shown; onChanged: (answer: ProjectSessions) => void }) {
  const now = useNow();
  return (
    <section className="talk" aria-label="Gates" data-testid="gates">
      <h2 className="talk-head">
        <IconHourglass size={18} stroke={1.6} aria-hidden />
        {plural(found.gates.length, "gated session")}
      </h2>
      <p className="talk-lede">
        A later session’s file edits on colliding work wait until each earlier member agrees or the project’s wait
        passes, or its member says it is different work; a refusal holds until the refusing session ends or goes idle.
        Reading, searching and planning go ahead.
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
                    Waits for {wait.on_my_work ? "your session" : <Who session={wait.earlier} />}, on{" "}
                    <Activity session={wait.earlier} />:{" "}
                    {wait.refused ? (
                      <b className="talk-left" data-testid="gate-refused">
                        {wait.on_my_work ? "you refused" : "refused"}, until that session ends or goes idle
                      </b>
                    ) : (
                      <time className="talk-left" dateTime={wait.until} data-testid="time-left">
                        {left(end - now)}
                      </time>
                    )}
                    {wait.on_my_work && (
                      <GateAnswer projectId={found.project_id} gate={gate} refused={wait.refused} onChanged={onChanged} />
                    )}
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

/** The handoff notes of sessions gone lately, written by those sessions or the server: read here, never written. */
function HandoffNotes({ notes }: { notes: SessionHandoffNote[] }) {
  return (
    <section className="talk" aria-label="Handoff notes" data-testid="handoff-notes">
      <h2 className="talk-head">
        <IconNotes size={18} stroke={1.6} aria-hidden />
        Handoff notes from sessions gone lately
      </h2>
      <ul className="talk-list">
        {notes.map((one) => (
          <li key={`${one.member_id} ${one.written_at}`} data-testid="handoff-note">
            <p className="talk-line">
              <b title={one.member_id}>{one.member_name}</b>’s session
              {[one.agent, one.repository].filter(Boolean).length > 0 &&
                ` in ${[one.agent, one.repository].filter(Boolean).join(", ")}`}
              {one.activity && (
                <>
                  , on <q>{one.activity}</q>
                </>
              )}
            </p>
            {one.done && (
              <p className="talk-text" data-testid="handoff-done">
                <b>Done:</b> {one.done}
              </p>
            )}
            {one.left && (
              <p className="talk-text" data-testid="handoff-left">
                <b>Left:</b> {one.left}
              </p>
            )}
            <p className="talk-meta">
              {one.by_server ? "Put together by the server, as the session left none" : "Left by the session"},{" "}
              <time dateTime={one.written_at}>{moment(one.written_at)}</time>
              {one.branch && <> · branch {one.branch}</>}
              {one.touched_files.length > 0 && <> · {one.touched_files.join(", ")}</>}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A reply to one message, sent from the signed-in member's session in the project to the message's sender. */
function Reply({
  projectId,
  message,
  textLimit,
  onChanged,
}: {
  projectId: string;
  message: SessionMessage;
  textLimit: number;
  onChanged: (answer: ProjectSessions) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [tried, setTried] = useState(false);
  const { busy, refusal, run } = useChange(onChanged);
  if (!open)
    return (
      <div className="talk-answer">
        <Button size="xs" variant="default" onClick={() => setOpen(true)} data-testid="reply">
          Reply to {message.sender_name}
        </Button>
      </div>
    );
  return (
    <form
      className="card-form talk-answer"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!text.trim()) return setTried(true);
        if (await run("send", () => sendMessage(projectId, message.sender_member_id, text))) {
          setText("");
          setTried(false);
          setOpen(false);
        }
      }}
    >
      <Textarea
        label={`Your reply to ${message.sender_name}`}
        description="Their session is shown it on its next step, as your words, never as an instruction."
        autosize
        minRows={2}
        maxRows={8}
        maxLength={textLimit}
        value={text}
        error={tried && !text.trim() ? "Write the reply first." : undefined}
        onChange={(event) => setText(event.currentTarget.value)}
        data-testid="reply-text"
      />
      <div className="card-form-actions">
        <Button size="xs" type="submit" loading={busy !== null} data-testid="reply-send">
          Send
        </Button>
        <Button size="xs" variant="default" disabled={busy !== null} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {refusal && <Refusal testid="reply-refused">{refusal}</Refusal>}
    </form>
  );
}

/** The messages the signed-in member's sessions sent or were sent: no one else's are ever here. */
function Messages({
  projectId,
  messages,
  textLimit,
  onChanged,
}: {
  projectId: string;
  messages: SessionMessage[];
  textLimit: number;
  onChanged: (answer: ProjectSessions) => void;
}) {
  return (
    <section className="talk" aria-label="Your sessions’ messages" data-testid="messages">
      <h2 className="talk-head">
        <IconMessage size={18} stroke={1.6} aria-hidden />
        Your sessions’ messages
      </h2>
      <ul className="talk-list">
        {messages.map((one) => (
          <li key={one.message_id} data-testid="message">
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
              {one.urgent && (
                <>
                  {" · "}
                  <b className="talk-urgent" data-testid="message-urgent">
                    {one.sent_by_me
                      ? "urgent: their session’s edits on this work wait for an answer"
                      : "urgent: your session’s edits on this work wait until you reply"}
                  </b>
                </>
              )}
            </p>
            <p className="talk-text" data-testid="message-text">
              {one.text}
            </p>
            {!one.sent_by_me && <Reply projectId={projectId} message={one} textLimit={textLimit} onChanged={onChanged} />}
          </li>
        ))}
      </ul>
    </section>
  );
}
