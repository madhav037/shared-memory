import { Button, Checkbox } from "@mantine/core";
import { IconHistory, IconScale } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import {
  decideChallenge,
  fetchChallenges,
  fetchMembers,
  type ChallengeDetail,
  type ChallengeList,
  type Decided,
  type RaisedChallenge,
} from "../api/client";
import { Amended } from "../components/Amended";
import { Placeholder, Rank, Refusal } from "../components/Bits";
import { Prose, Source, ViewSwitch, type ReadingView } from "../components/Prose";
import { useContents } from "../lib/contents";
import { whatChanges } from "../lib/changes";
import { changed, offerDiff } from "../lib/diff";
import { day, memoryUrl, moment } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** Everything disputed: what is waiting for this member's decision, and what they have asked of others. */
export function Challenges({
  readsAudit,
  onDecided,
}: {
  readsAudit: boolean;
  /** Told what is still waiting once a decision lands, so the masthead's count needn't wait for the next page. */
  onDecided?: (left: ChallengeList) => void;
}) {
  const { answer, refused, setAnswer } = useAsked((signal) => fetchChallenges(signal), []);
  const { answer: team } = useAsked((signal) => fetchMembers(signal), []);
  const [slip, setSlip] = useState<Slip | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const names = new Map((team?.members ?? []).map((one) => [one.member_id, one.name]));
  // A member is their name here; their member ID belongs on Team.
  const who = (memberId: string) => names.get(memberId) ?? memberId;

  const decided = (said: Slip, left: ChallengeList) => {
    setSlip(said);
    setAnswer(left);
    onDecided?.(left);
  };
  const dismiss = () => {
    setSlip(null);
    heading.current?.focus();
  };

  return (
    <div className="medium">
      <h1 className="page-title wide">Challenges</h1>
      <p className="standfirst">
        A challenge asks for a memory to be superseded or retired, or for one to join a foundation. You decide the ones
        waiting here as their author, or for the reason each one gives.
      </p>

      {refused && <Refusal>{refused}</Refusal>}
      {!answer && !refused && <Placeholder lines={8} />}
      {answer && (
        <>
          <h2 className="section-heading" ref={heading} tabIndex={-1}>
            Waiting for your decision
          </h2>
          {/* Always on the page, so what was decided is announced when it arrives. */}
          <div role="status" data-testid="decided-region">
            {slip && <DecidedSlip slip={slip} readsAudit={readsAudit} onDismiss={dismiss} />}
          </div>
          {answer.waiting.length === 0 ? (
            <p className="empty" data-testid="nothing-waiting">
              {slip ? "Nothing else is waiting for your decision." : "Nothing is waiting for your decision."}
            </p>
          ) : (
            <Waiting waiting={answer.waiting} who={who} onDecided={decided} />
          )}
          <Raised raised={answer.raised} who={who} />
        </>
      )}
    </div>
  );
}

/** What the member just decided: the server's answer, with the challenge it was about. */
type Slip = { decided: Decided; challenge: ChallengeDetail; others: number };

/** Says what a decision did, in place of the challenge it decided, until the member dismisses it or leaves. */
function DecidedSlip({ slip, readsAudit, onDismiss }: { slip: Slip; readsAudit: boolean; onDismiss: () => void }) {
  const here = useRef<HTMLDivElement>(null);
  useEffect(() => here.current?.focus(), [slip]);

  const { decided, challenge, others } = slip;
  const adding = challenge.kind === "add";
  // An "add" has no challenged memory: its target stands for the foundation.
  const foundation = adding ? challenge.target.title : "";
  const replaced = challenge.target.title;
  const offered = challenge.challenger?.title;
  const rejected = decided.decision === "rejected";
  const readable = adding ? (challenge.challenger?.path ?? challenge.target.path) : challenge.target.path;
  const what = () => {
    if (adding) {
      return (
        <>
          <b>You {rejected ? "rejected" : "accepted"} it.</b> <span className="decided-name">‘{offered}’</span>{" "}
          {rejected ? "stays out of" : "is now in"} the {foundation} foundation.
        </>
      );
    }
    if (rejected) {
      return (
        <>
          <b>You rejected it.</b> <span className="decided-name">‘{replaced}’</span> stays as it is.
        </>
      );
    }
    if (offered) {
      return (
        <>
          <b>You accepted it.</b> <span className="decided-name">‘{offered}’</span> now supersedes{" "}
          <span className="decided-name">‘{replaced}’</span>.
        </>
      );
    }
    return (
      <>
        <b>You accepted it.</b> <span className="decided-name">‘{replaced}’</span> is retired.
      </>
    );
  };
  return (
    <div
      className={decided.in_force ? "decided appear" : "decided retired appear"}
      ref={here}
      tabIndex={-1}
      data-testid="decided"
    >
      <p className="decided-what">
        <IconScale size={18} stroke={1.6} aria-hidden />
        <span>
          {what()}
          {decided.decision === "accepted" && others > 0 && (
            <> Every other challenge against it is closed, and whoever raised it is told why.</>
          )}
        </span>
      </p>
      <p className="decided-links">
        <Link className="quiet-link" to={memoryUrl(decided.in_force ?? readable)} data-testid="decided-read">
          Read it
        </Link>
        {readsAudit && (
          <Link className="quiet-link" to="/audit" data-testid="decided-audit">
            <IconHistory size={14} stroke={1.6} aria-hidden />
            See it in the audit log
          </Link>
        )}
        <button type="button" className="quiet-link decided-dismiss" onClick={onDismiss} data-testid="decided-dismiss">
          Dismiss
        </button>
      </p>
    </div>
  );
}

function Waiting({
  waiting,
  who,
  onDecided,
}: {
  waiting: ChallengeDetail[];
  who: (memberId: string) => string;
  onDecided: (slip: Slip, left: ChallengeList) => void;
}) {
  // One decision at a time: the ref stops a second click before React has re-rendered the buttons as busy.
  const [deciding, setDeciding] = useState<{ challengeId: number; decision: Choice } | null>(null);
  const busy = useRef(false);
  const [refused, setRefused] = useState<{ challengeId: number; message: string } | null>(null);
  const [view, setView] = useState<ReadingView>("text");
  const [marked, setMarked] = useState(true);
  const { refresh } = useContents();

  const decide = async (challenge: ChallengeDetail, decision: Choice, others: number) => {
    if (busy.current) return;
    busy.current = true;
    setDeciding({ challengeId: challenge.challenge_id, decision });
    setRefused(null);
    try {
      const answer = await decideChallenge(challenge.challenge_id, decision);
      refresh();
      onDecided({ decided: answer.decided, challenge, others }, { waiting: answer.waiting, raised: answer.raised });
    } catch (problem) {
      setRefused({ challengeId: challenge.challenge_id, message: (problem as Error).message });
    } finally {
      busy.current = false;
      setDeciding(null);
    }
  };

  // Challenges to a foundation are shown apart: a keeper or project lead decides them, not a memory's author.
  const ordinary = waiting.filter((one) => one.foundation === null);
  const foundations = waiting.filter((one) => one.foundation !== null);
  // Several challenges can be against one memory; they are decided together, so they are shown together.
  const memories = new Map<string, ChallengeDetail[]>();
  for (const one of ordinary) memories.set(one.target.path, [...(memories.get(one.target.path) ?? []), one]);

  const proposal = (challenge: ChallengeDetail, others: number) => (
    <Proposal
      key={challenge.challenge_id}
      challenge={challenge}
      who={who}
      view={view}
      marked={marked}
      deciding={deciding}
      refused={refused?.challengeId === challenge.challenge_id ? refused.message : null}
      onDecide={(decision) => decide(challenge, decision, others)}
    />
  );

  return (
    <>
    {ordinary.length > 0 && (
      <div className="waiting" data-testid="waiting">
        <ViewSwitch view={view} onChange={setView} />
        <div className="waiting-marks">
          {view === "text" && (
            <Checkbox
              radius={0}
              size="xs"
              label="Show what each offer takes out and puts in"
              checked={marked}
              onChange={(event) => setMarked(event.currentTarget.checked)}
            />
          )}
        </div>
        {[...memories].map(([path, against]) => {
          const first = against[0];
          if (!first) return null;
          return (
            <section className="dispute" key={path} aria-label={`Challenges against ${first.target.title}`}>
              <div className="dispute-head">
                <h3>
                  <Link to={memoryUrl(first.target.path)}>{first.target.title}</Link>
                </h3>
                <Rank level={first.target.level} />
                {against.length > 1 && <span className="mark alert">{against.length} challenges</span>}
              </div>
              {against.length > 1 && (
                <p className="dispute-note">
                  Accept at most one: accepting it closes the others, and whoever raised them is told why.
                </p>
              )}
              {against.map((challenge) => proposal(challenge, against.length - 1))}
            </section>
          );
        })}
      </div>
    )}
    {foundations.length > 0 && (
      <>
        <h2 className="section-heading">Foundation challenges</h2>
        {ordinary.length === 0 && <ViewSwitch view={view} onChange={setView} />}
        <div className="waiting" data-testid="foundation-challenges">
          {foundations.map((challenge) => {
            const shown = challenge.kind === "add" ? challenge.challenger : challenge.target;
            return (
              <section
                className="dispute"
                key={challenge.challenge_id}
                aria-label={`Foundation challenge to the ${challenge.foundation_name} foundation`}
              >
                <div className="dispute-head">
                  <h3>{shown && <Link to={memoryUrl(shown.path)}>{shown.title}</Link>}</h3>
                  <span className="mark strong" data-testid="foundation-mark">
                    {challenge.foundation_name} foundation
                  </span>
                </div>
                {proposal(challenge, 0)}
              </section>
            );
          })}
        </div>
      </>
    )}
    </>
  );
}

/** Why a challenge against another member's memory is this member's to decide. */
const WHY_YOURS: Record<Exclude<ChallengeDetail["decides_as"], "author">, string> = {
  lead: "yours to decide as a project lead",
  keeper: "yours to decide as a keeper of the foundation",
  admin: "yours to decide as an admin",
  fallback: "nobody has decided in time, so anyone may",
  author_left: "its author has left the team, so anyone may",
};

type Choice = "accept" | "reject";

function Proposal({
  challenge,
  who,
  view,
  marked,
  deciding,
  refused,
  onDecide,
}: {
  challenge: ChallengeDetail;
  who: (memberId: string) => string;
  view: ReadingView;
  marked: boolean;
  /** The decision being sent, on this challenge or another; while one is, none can be. */
  deciding: { challengeId: number; decision: Choice } | null;
  refused: string | null;
  onDecide: (decision: Choice) => void;
}) {
  const pressed = (decision: Choice) =>
    deciding?.challengeId === challenge.challenge_id && deciding.decision === decision;
  // Busy, not disabled: a disabled button drops the focus it holds, and the guard in decide refuses a second send.
  const busy = deciding ? { "data-disabled": true, "aria-disabled": true } : {};
  const offered = challenge.challenger;
  // An "add" brings a memory into a foundation: there is nothing in it to compare the memory with.
  const adding = challenge.kind === "add";
  const pieces = offered && marked && !adding ? offerDiff(challenge.target.body, offered.body) : null;
  const changes = offered && !adding ? whatChanges(challenge.target.body, offered.body) : null;
  return (
    <div className="proposal">
      <p className="proposal-by">
        <IconScale size={14} stroke={1.6} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />
        <b>{who(challenge.raised_by)}</b> wants to{" "}
        {adding
          ? `add it to the ${challenge.foundation_name} foundation`
          : challenge.kind === "retire"
            ? "retire it"
            : "supersede it"}{" "}
        ·{" "}
        {moment(challenge.raised_at)}
        {challenge.decides_as !== "author" && (
          <span data-testid="decides-as"> · {WHY_YOURS[challenge.decides_as]}</span>
        )}
      </p>
      {challenge.reasoning && (
        <div className="reasoning" data-testid="reasoning">
          <p className="reasoning-head">Reasoning</p>
          <p className="reasoning-text" data-testid="reasoning-text">{challenge.reasoning}</p>
        </div>
      )}
      {changes && (
        <div className="what-changes" data-testid="what-changes">
          <p className="what-changes-head">If you accept this, here is what would be different</p>
          {changes.differences.length > 0 ? (
            <ul>
              {changes.differences.map((difference) => (
                <li key={`${difference.kind}-${difference.label}`}>
                  <b>{difference.label}</b>{" "}
                  {difference.kind === "changed" ? (
                    <>
                      changes from <q>{difference.from}</q> to <q>{difference.to}</q>
                    </>
                  ) : difference.kind === "added" ? (
                    <>is added: <q>{difference.to}</q></>
                  ) : (
                    <>is dropped, where it now says <q>{difference.from}</q></>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="what-changes-none">
              The parts both of them set out are the same. The difference is in the words around them, below.
            </p>
          )}
          {changes.unchanged.length > 0 && (
            <p className="what-changes-same">Unchanged: {changes.unchanged.join(", ")}.</p>
          )}
        </div>
      )}
      <div className="facing" data-testid="facing">
        {adding ? (
          <div>
            <span className="title">{challenge.target.title} foundation</span>
            <p className="by">Where it would be added</p>
          </div>
        ) : (
          <div>
            <Link className="title" to={memoryUrl(challenge.target.path)}>
              {challenge.target.title}
            </Link>
            <p className="by">As it stands now, by {who(challenge.target.author)}</p>
            <div className="body">
              {view === "source" ? (
                <Source text={challenge.target.body} testid="facing-source" />
              ) : (
                <Prose testid="facing-text">{challenge.target.body}</Prose>
              )}
            </div>
          </div>
        )}
        <div>
          {offered ? (
            <>
              <Link className="title" to={memoryUrl(offered.path)}>
                {offered.title}
              </Link>
              <p className="by">
                {adding ? "Offered for the foundation" : "Offered in its place"} by {who(offered.author)}
              </p>
              <div className="body">
                {view === "source" ? (
                  <Source text={offered.body} testid="facing-source" />
                ) : pieces && changed(pieces) ? (
                  <Amended pieces={pieces} source="this offer" testid="amended" />
                ) : (
                  <Prose testid="facing-text">{offered.body}</Prose>
                )}
              </div>
            </>
          ) : (
            <>
              <span className="title" style={{ color: "var(--ink-2)" }}>
                Nothing in its place
              </span>
              <p className="by">Asked for by {who(challenge.raised_by)}</p>
              <p className="body retire-it">Retire it: {who(challenge.raised_by)} says it is no longer true.</p>
            </>
          )}
        </div>
      </div>
      <div className="decide" aria-busy={deciding?.challengeId === challenge.challenge_id || undefined}>
        <Button size="sm" {...busy} onClick={() => onDecide("accept")} data-testid={`accept-${challenge.challenge_id}`}>
          {pressed("accept")
            ? "Deciding…"
            : adding
              ? "Accept: add it to the foundation"
              : offered
                ? "Accept: supersede it"
                : "Accept: retire it"}
        </Button>
        <Button
          size="sm"
          variant="default"
          {...busy}
          onClick={() => onDecide("reject")}
          data-testid={`reject-${challenge.challenge_id}`}
        >
          {pressed("reject") ? "Deciding…" : adding ? "Reject: keep it out" : "Reject: keep it as it is"}
        </Button>
      </div>
      {refused && <Refusal testid="decide-refused">{refused}</Refusal>}
    </div>
  );
}

const STATES: Record<string, string> = {
  open: "Waiting",
  accepted: "Accepted",
  rejected: "Rejected",
  closed: "Closed",
  withdrawn: "Withdrawn",
};

function Raised({ raised, who }: { raised: RaisedChallenge[]; who: (memberId: string) => string }) {
  return (
    <>
      <h2 className="section-heading">Challenges you raised</h2>
      {raised.length === 0 ? (
        <p className="empty">
          You haven’t raised any. A challenge is raised from your coding agent, when you promote a memory that should replace
          someone else’s, or from a memory’s page here, when you retire one that isn’t yours.
        </p>
      ) : (
        <div className="scroll-x">
          <table className="register" data-testid="raised">
            <thead>
              <tr>
                <th scope="col">Raised</th>
                <th scope="col">Against</th>
                <th scope="col">Asking</th>
                <th scope="col">How it ended</th>
              </tr>
            </thead>
            <tbody>
              {raised.map((one) => (
                <tr key={one.challenge_id}>
                  <td className="aside" style={{ whiteSpace: "nowrap" }}>{day(one.raised_at)}</td>
                  <td className="primary">
                    {one.kind === "add" ? (
                      <>{one.target_title} foundation</>
                    ) : (
                      <Link to={memoryUrl(one.target_path)} style={{ color: "inherit" }}>
                        {one.target_title}
                      </Link>
                    )}
                  </td>
                  <td>
                    {one.kind === "add" ? "to add a memory" : one.kind === "retire" ? "to retire it" : "to supersede it"}
                    {one.reasoning && (
                      <div className="raised-reasoning" data-testid="raised-reasoning">
                        {one.reasoning}
                      </div>
                    )}
                  </td>
                  <td data-label="How it ended">
                    <b style={{ color: one.state === "accepted" ? "var(--accent)" : "var(--ink)" }}>{STATES[one.state] ?? one.state}</b>
                    {one.decided_by && (
                      <div style={{ fontSize: "0.8125rem", color: "var(--ink-3)" }}>
                        by {who(one.decided_by)}
                        {one.decided_at ? `, ${day(one.decided_at)}` : ""}
                        {one.explanation ? ` — ${one.explanation}` : ""}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
