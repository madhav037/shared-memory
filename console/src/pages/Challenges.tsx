import { Button, Checkbox, Textarea } from "@mantine/core";
import { IconHistory, IconScale } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import {
  decideChallenge,
  fetchChallenges,
  fetchMembers,
  fetchMemoryAt,
  type ChallengeDetail,
  type ChallengeList,
  type DoubtEvidence,
  type Decided,
  type RaisedChallenge,
} from "../api/client";
import { Amended } from "../components/Amended";
import { Placeholder, Rank, Refusal } from "../components/Bits";
import { Compared } from "../components/Compared";
import { HiddenWarning, Told } from "../components/Told";
import { Prose, Source, ViewSwitch, type ReadingView } from "../components/Prose";
import { useContents } from "../lib/contents";
import { whatChanges } from "../lib/changes";
import { changed, offerDiff } from "../lib/diff";
import { asks, REASON_NAMES } from "../lib/challenge";
import { day, memoryUrl, moment } from "../lib/format";
import { visible } from "../lib/hidden";
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
  // A memory's page links here for the challenges against that one memory, its doubts among them.
  const [asked] = useSearchParams();
  const only = asked.get("path");
  const { answer: company } = useAsked((signal) => fetchMembers(signal), []);
  const [slip, setSlip] = useState<Slip | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const names = new Map((company?.members ?? []).map((one) => [one.member_id, one.name]));
  // A member is their name here; their member ID belongs on Company.
  const who = (memberId: string) => visible(names.get(memberId) ?? memberId);

  const decided = (said: Slip, left: ChallengeList) => {
    setSlip(said);
    setAnswer(left);
    onDecided?.(left);
  };
  const dismiss = () => {
    setSlip(null);
    heading.current?.focus();
  };
  const shown = !answer ? [] : only ? answer.waiting.filter((one) => one.target.path === only) : answer.waiting;

  return (
    <div className="medium">
      <h1 className="page-title wide">Challenges</h1>
      <p className="standfirst">
        A challenge asks for a memory to be superseded or retired, says a session doubts it, or asks for one to join a
        foundation or department memory. You decide the ones waiting here as their author, or for the reason each one
        gives.
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
          {only && (
            <p className="showing-one" data-testid="showing-one">
              Only the challenges against one memory. <Link to="/challenges">Show every challenge</Link>
            </p>
          )}
          {shown.length === 0 ? (
            <p className="empty" data-testid="nothing-waiting">
              {slip ? "Nothing else is waiting for your decision." : "Nothing is waiting for your decision."}
            </p>
          ) : (
            <Waiting waiting={shown} who={who} onDecided={decided} />
          )}
          {only && <OthersDoubts path={only} who={who} />}
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
  const levelled = decided.decision === "kept_exception" || decided.decision === "followed";
  const promoting = challenge.kind === "promote";
  const adding = challenge.kind === "add" || promoting;
  // An "add" or a "promote" has no challenged memory: its target stands for the foundation or the department.
  const foundation = adding ? challenge.target.title : "";
  const replaced = challenge.target.title;
  const offered = challenge.challenger?.title;
  const rejected = decided.decision === "rejected";
  const readable = adding ? (challenge.challenger?.path ?? challenge.target.path) : challenge.target.path;
  const what = () => {
    if (levelled) {
      return decided.decision === "kept_exception" ? (
        <>
          <b>You kept an exception.</b> <span className="decided-name">‘{offered}’</span> holds over{" "}
          <span className="decided-name">‘{replaced}’</span>, with your reason.
        </>
      ) : (
        <>
          <b>You followed it.</b> <span className="decided-name">‘{offered}’</span> is retired, and{" "}
          <span className="decided-name">‘{replaced}’</span> holds.
        </>
      );
    }
    if (promoting) {
      return (
        <>
          <b>You {rejected ? "rejected" : "accepted"} it.</b> <span className="decided-name">‘{offered}’</span>{" "}
          {rejected ? "stays personal memory." : `is now ${foundation} department memory.`}
        </>
      );
    }
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
          {!levelled && decided.decision === "accepted" && others > 0 && (
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
  // A decision is made on what coding agents will read, so the files come first, word for word.
  const [view, setView] = useState<ReadingView>("source");
  const [marked, setMarked] = useState(true);
  const { refresh } = useContents();

  const decide = async (challenge: ChallengeDetail, decision: Choice, others: number, reason?: string) => {
    if (busy.current) return;
    busy.current = true;
    setDeciding({ challengeId: challenge.challenge_id, decision });
    setRefused(null);
    try {
      const answer = await decideChallenge(challenge.challenge_id, decision, reason);
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
  // So are promotions into department memory: its department leads decide them.
  // So are level contradictions: the narrower level's leads keep an exception or follow the broader memory.
  const ordinary = waiting.filter(
    (one) => one.foundation === null && one.kind !== "promote" && one.kind !== LEVEL_CONTRADICTION,
  );
  const foundations = waiting.filter((one) => one.foundation !== null);
  const departments = waiting.filter((one) => one.kind === "promote");
  const levels = waiting.filter((one) => one.kind === LEVEL_CONTRADICTION);
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
                  <Link to={memoryUrl(first.target.path)}>{visible(first.target.title)}</Link>
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
                  <h3>{shown && <Link to={memoryUrl(shown.path)}>{visible(shown.title)}</Link>}</h3>
                  <span className="mark strong" data-testid="foundation-mark">
                    {visible(challenge.foundation_name ?? "")} foundation
                  </span>
                </div>
                {proposal(challenge, 0)}
              </section>
            );
          })}
        </div>
      </>
    )}
    {departments.length > 0 && (
      <>
        <h2 className="section-heading">Department challenges</h2>
        {ordinary.length === 0 && foundations.length === 0 && <ViewSwitch view={view} onChange={setView} />}
        <div className="waiting" data-testid="department-challenges">
          {departments.map((challenge) => (
            <section
              className="dispute"
              key={challenge.challenge_id}
              aria-label={`Department challenge to ${challenge.target.title} department memory`}
            >
              <div className="dispute-head">
                <h3>
                  {challenge.challenger && (
                    <Link to={memoryUrl(challenge.challenger.path)}>{visible(challenge.challenger.title)}</Link>
                  )}
                </h3>
                <span className="mark strong" data-testid="department-mark">
                  {visible(challenge.target.title)} department
                </span>
              </div>
              {proposal(challenge, 0)}
            </section>
          ))}
        </div>
      </>
    )}
    {levels.length > 0 && (
      <>
        <h2 className="section-heading">Level contradictions</h2>
        {ordinary.length === 0 && foundations.length === 0 && departments.length === 0 && (
          <ViewSwitch view={view} onChange={setView} />
        )}
        <div className="waiting" data-testid="level-contradictions">
          {levels.map((challenge) => (
            <LevelContradiction
              key={challenge.challenge_id}
              challenge={challenge}
              who={who}
              view={view}
              deciding={deciding}
              refused={refused?.challengeId === challenge.challenge_id ? refused.message : null}
              onDecide={(decision, reason) => decide(challenge, decision, 0, reason)}
            />
          ))}
        </div>
      </>
    )}
    </>
  );
}

const LEVEL_CONTRADICTION = "level_contradiction";

/** A level contradiction: the narrower memory beside the broader one it contradicts, each with its level. Keeping an
 * exception records a reason; following retires the narrower memory. Neither changes what a memory says (ADR-0009). */
function LevelContradiction({
  challenge,
  who,
  view,
  deciding,
  refused,
  onDecide,
}: {
  challenge: ChallengeDetail;
  who: (memberId: string) => string;
  view: ReadingView;
  deciding: { challengeId: number; decision: Choice } | null;
  refused: string | null;
  onDecide: (decision: Choice, reason?: string) => void;
}) {
  const [reason, setReason] = useState("");
  const narrower = challenge.challenger;
  const broader = challenge.target;
  const pressed = (decision: Choice) =>
    deciding?.challengeId === challenge.challenge_id && deciding.decision === decision;
  const busy = deciding ? { "data-disabled": true, "aria-disabled": true } : {};
  const where = narrower?.level === "department" ? "department" : "project";
  return (
    <section
      className="dispute"
      aria-label={`Level contradiction: ${narrower?.title ?? ""} against ${broader.title}`}
      data-testid="level-contradiction"
    >
      <div className="proposal">
        <p className="proposal-by">
          <IconScale size={14} stroke={1.6} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />
          <b>{who(challenge.raised_by)}</b>’s {where} memory contradicts {broader.level} memory · waiting since{" "}
          {moment(challenge.raised_at)}
          {challenge.decides_as !== "author" && (
            <span data-testid="decides-as"> · {WHY_YOURS[challenge.decides_as]}</span>
          )}
        </p>
        <p className="dispute-note">Until you decide, the {where} memory holds for its {where}.</p>
        <HiddenWarning texts={wordsOf(challenge)} />
        <div className="facing" data-testid="facing">
          {[narrower, broader].map(
            (side) =>
              side && (
                <div key={side.path} data-testid="level-side">
                  <Rank level={side.level} />
                  <Link className="title" to={memoryUrl(side.path)}>
                    {visible(side.title)}
                  </Link>
                  <Told summary={side.summary} tiedFiles={side.tied_files} />
                  <p className="by">By {who(side.author)}</p>
                  <div className="body">
                    {view === "source" ? (
                      <Source text={side.source} testid="facing-source" />
                    ) : (
                      <Prose testid="facing-text">{side.body}</Prose>
                    )}
                  </div>
                </div>
              ),
          )}
        </div>
        <Textarea
          radius={0}
          label={`Why this ${where} differs, to keep an exception`}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
          data-testid="exception-reason-input"
        />
        <div className="decide" aria-busy={deciding?.challengeId === challenge.challenge_id || undefined}>
          <Button size="sm" {...busy} onClick={() => onDecide("keep_exception", reason)}>
            {pressed("keep_exception") ? "Deciding…" : "Keep an exception"}
          </Button>
          <Button size="sm" variant="default" {...busy} onClick={() => onDecide("follow")}>
            {pressed("follow") ? "Deciding…" : `Follow: retire the ${where} memory`}
          </Button>
        </div>
        {refused && <Refusal>{refused}</Refusal>}
      </div>
    </section>
  );
}

/** Why a challenge against another member's memory is this member's to decide. */
const WHY_YOURS: Record<Exclude<ChallengeDetail["decides_as"], "author">, string> = {
  lead: "yours to decide as a project lead",
  keeper: "yours to decide as a keeper of the foundation",
  admin: "yours to decide as an admin",
  fallback: "nobody has decided in time, so anyone may",
  author_left: "its author has left the company, so anyone may",
  department_lead: "yours to decide as a department lead",
};

type Choice = "accept" | "reject" | "keep_exception" | "follow";


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
  // An "add" brings a memory into a foundation, and a "promote" into department memory: there is nothing there to
  // compare the memory with.
  const promoting = challenge.kind === "promote";
  const adding = challenge.kind === "add" || promoting;
  // An offered memory deleted or moved since is no longer there to compare: it is said to be gone, not diffed as empty.
  const gone = offered?.status === "gone";
  const compared = offered && !adding && !gone ? offered : null;
  const pieces = compared && marked ? offerDiff(challenge.target.body, compared.body) : null;
  const changes = compared ? whatChanges(challenge.target.body, compared.body) : null;
  return (
    <div className="proposal">
      <p className="proposal-by">
        <IconScale size={14} stroke={1.6} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />
        {challenge.reason ? (
          <DoubtBy raisedBy={challenge.raised_by} reason={challenge.reason} count={challenge.count} who={who} />
        ) : (
          <>
            <b>{who(challenge.raised_by)}</b> wants to {asks(challenge)}
          </>
        )}{" "}
        ·{" "}
        {moment(challenge.raised_at)}
        {challenge.decides_as !== "author" && (
          <span data-testid="decides-as"> · {WHY_YOURS[challenge.decides_as]}</span>
        )}
      </p>
      {challenge.reasoning && (
        <div className="reasoning" data-testid="reasoning">
          <p className="reasoning-head">Reasoning</p>
          <p className="reasoning-text" data-testid="reasoning-text">{visible(challenge.reasoning)}</p>
        </div>
      )}
      <HiddenWarning texts={wordsOf(challenge)} />
      {challenge.evidence.length > 0 && <EvidenceList evidence={challenge.evidence} who={who} />}
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
            <span className="title">
              {visible(challenge.target.title)} {promoting ? "department memory" : "foundation"}
            </span>
            <p className="by">Where it would be added</p>
          </div>
        ) : (
          <div>
            <Link className="title" to={memoryUrl(challenge.target.path)}>
              {visible(challenge.target.title)}
            </Link>
            <Told summary={challenge.target.summary} tiedFiles={challenge.target.tied_files} />
            <p className="by">As it stands now, by {who(challenge.target.author)}</p>
            <div className="body">
              {view === "source" ? (
                compared ? (
                  <Compared before={challenge.target.source} after={compared.source} side="now" />
                ) : (
                  <Source text={challenge.target.source} testid="facing-source" />
                )
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
                {visible(offered.title)}
              </Link>
              <Told summary={offered.summary} tiedFiles={offered.tied_files} />
              <p className="by">
                {promoting ? "Offered for department memory" : adding ? "Offered for the foundation" : "Offered in its place"}{" "}
                by {who(offered.author)}
              </p>
              <div className="body">
                {gone ? (
                  <p className="retire-it" data-testid="offer-gone">
                    The offered memory is gone: it was deleted or moved after the challenge was raised.
                  </p>
                ) : view === "source" ? (
                  adding ? (
                    <Source text={offered.source} testid="facing-source" />
                  ) : (
                    <Compared before={challenge.target.source} after={offered.source} side="offered" />
                  )
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
              {challenge.reason ? (
                <>
                  <p className="by">
                    Doubted by {challenge.count === 1 ? who(challenge.raised_by) : `${challenge.count} members`}
                  </p>
                  <p className="body retire-it">
                    Retire it if the evidence holds. Reject it and the memory stands, no longer in doubt.
                  </p>
                </>
              ) : (
                <>
                  <p className="by">Asked for by {who(challenge.raised_by)}</p>
                  <p className="body retire-it">Retire it: {who(challenge.raised_by)} says it is no longer true.</p>
                </>
              )}
            </>
          )}
        </div>
      </div>
      <div className="decide" aria-busy={deciding?.challengeId === challenge.challenge_id || undefined}>
        <Button size="sm" {...busy} onClick={() => onDecide("accept")} data-testid={`accept-${challenge.challenge_id}`}>
          {pressed("accept")
            ? "Deciding…"
            : promoting
              ? "Accept: promote it into department memory"
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
          {pressed("reject")
            ? "Deciding…"
            : promoting
              ? "Reject: it stays personal"
              : adding
                ? "Reject: keep it out"
                : "Reject: keep it as it is"}
        </Button>
      </div>
      {refused && <Refusal testid="decide-refused">{refused}</Refusal>}
    </div>
  );
}

/** Who doubts a memory first, for which reason, and how many members have joined them. */
function DoubtBy({
  raisedBy,
  reason,
  count,
  who,
}: {
  raisedBy: string;
  reason: keyof typeof REASON_NAMES;
  count: number | null;
  who: (memberId: string) => string;
}) {
  return (
    <>
      <b>{who(raisedBy)}</b> doubts it{" "}
      <span className="mark alert" data-testid="doubt-reason">
        {REASON_NAMES[reason]}
      </span>
      {count !== null && count > 1 && (
        <>
          {" "}
          <span className="mark" data-testid="doubt-count" title={`${count} members have raised it`}>
            +{count - 1}
          </span>
        </>
      )}
    </>
  );
}

/** The open doubts against one memory that this member can read but not decide: shown, never decided here. */
function OthersDoubts({ path, who }: { path: string; who: (memberId: string) => string }) {
  const { answer } = useAsked((signal) => fetchMemoryAt(path, signal), [path]);
  const doubts = (answer?.open_challenges ?? []).filter((one) => one.reason !== null && !one.may_decide);
  if (!answer || doubts.length === 0) return null;
  return (
    <section data-testid="others-doubts">
      <h2 className="section-heading">Open doubts about {answer.title}</h2>
      <p className="standfirst">
        {answer.author_name}
        {answer.level === "company" ? "" : ", a project lead"} or an admin decides these. Until then, recall ranks the
        memory lower and marks it for every coding agent.
      </p>
      {doubts.map((one) => (
        <div className="proposal" key={one.challenge_id} data-testid="others-doubt">
          <p className="proposal-by">
            <IconScale size={14} stroke={1.6} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />
            {one.reason && <DoubtBy raisedBy={one.raised_by} reason={one.reason} count={one.count} who={who} />}
          </p>
          {one.evidence.length > 0 && <EvidenceList evidence={one.evidence} who={who} />}
        </div>
      ))}
    </section>
  );
}

/** Every raise of a doubt, the first raiser's first: who, when, why, and the line of code it quotes. */
function EvidenceList({ evidence, who }: { evidence: DoubtEvidence[]; who: (memberId: string) => string }) {
  return (
    <div className="evidence" data-testid="evidence">
      <p className="reasoning-head">Evidence</p>
      <ol>
        {evidence.map((each, place) => (
          <li key={place} data-testid="evidence-entry">
            <p className="evidence-by">
              <b>{who(each.member_id)}</b> · {moment(each.raised_at)}
            </p>
            {each.reasoning && <p className="reasoning-text">{visible(each.reasoning)}</p>}
            {each.code_reference && (
              <p className="evidence-code">
                <code className="path" data-testid="evidence-reference">
                  {each.code_reference}
                </code>
                {each.quoted_line && <code className="quoted">{visible(each.quoted_line)}</code>}
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Every word of a challenge a coding agent may be given: both memories, the reasoning and the evidence. */
function wordsOf(challenge: ChallengeDetail): (string | null)[] {
  const sides = [challenge.target, challenge.challenger].flatMap((side) =>
    side ? [side.title, side.summary, side.body, side.source, ...side.tied_files] : [],
  );
  return [challenge.reasoning, ...sides, ...challenge.evidence.flatMap((each) => [each.reasoning, each.quoted_line])];
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
                    {one.kind === "add" || one.kind === "promote" ? (
                      <>
                        {one.target_title} {one.kind === "add" ? "foundation" : "department memory"}
                      </>
                    ) : (
                      <Link to={memoryUrl(one.target_path)} style={{ color: "inherit" }}>
                        {one.target_title}
                      </Link>
                    )}
                  </td>
                  <td>
                    to {asks(one)}
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
