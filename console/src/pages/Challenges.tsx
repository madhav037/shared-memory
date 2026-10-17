import { Button, Checkbox } from "@mantine/core";
import { IconScale } from "@tabler/icons-react";
import { useState } from "react";
import { Link } from "react-router";

import {
  decideChallenge,
  fetchChallenges,
  fetchMembers,
  type ChallengeDetail,
  type RaisedChallenge,
} from "../api/client";
import { Tracked } from "../components/Tracked";
import { Placeholder, Rank, Refusal } from "../components/Bits";
import { useContents } from "../lib/contents";
import { whatChanges } from "../lib/changes";
import { changed, lineDiff } from "../lib/diff";
import { day, memoryUrl, moment } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** Everything disputed: what is waiting for this member's decision, and what they have asked of others. */
export function Challenges() {
  const { answer, refused, reload } = useAsked((signal) => fetchChallenges(signal), []);
  const { answer: team } = useAsked((signal) => fetchMembers(signal), []);
  const names = new Map((team?.members ?? []).map((one) => [one.member_id, one.name]));
  const who = (memberId: string) => (names.get(memberId) ? `${names.get(memberId)} (${memberId})` : memberId);

  return (
    <div className="medium">
      <h1 className="page-title wide">Challenges</h1>
      <p className="standfirst">
        A challenge asks for a memory to be superseded or retired. You decide the ones waiting here as their author, or for
        the reason each one gives.
      </p>

      {refused && <Refusal>{refused}</Refusal>}
      {!answer && !refused && <Placeholder lines={8} />}
      {answer && (
        <>
          <h2 className="section-heading">Waiting for your decision</h2>
          {answer.waiting.length === 0 ? (
            <p className="empty" data-testid="nothing-waiting">
              Nothing is waiting for your decision.
            </p>
          ) : (
            <Waiting waiting={answer.waiting} who={who} onDecided={reload} />
          )}
          <Raised raised={answer.raised} who={who} />
        </>
      )}
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
  onDecided: () => void;
}) {
  const [refused, setRefused] = useState<string | null>(null);
  const [marked, setMarked] = useState(false);
  const { refresh } = useContents();

  const decide = async (challengeId: number, decision: "accept" | "reject") => {
    try {
      await decideChallenge(challengeId, decision);
      setRefused(null);
      refresh();
      onDecided();
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  // Several challenges can be against one memory; they are decided together, so they are shown together.
  const memories = new Map<string, ChallengeDetail[]>();
  for (const one of waiting) memories.set(one.target.path, [...(memories.get(one.target.path) ?? []), one]);

  return (
    <div data-testid="waiting">
      <Checkbox
        radius={0}
        size="xs"
        label="Show what each offer takes out and puts in"
        checked={marked}
        onChange={(event) => setMarked(event.currentTarget.checked)}
        style={{ margin: "4px 0 14px" }}
      />
      {refused && <Refusal testid="decide-refused">{refused}</Refusal>}
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
            {against.map((challenge) => (
              <Proposal key={challenge.challenge_id} challenge={challenge} who={who} marked={marked} onDecide={decide} />
            ))}
          </section>
        );
      })}
    </div>
  );
}

/** Why a challenge against another member's memory is this member's to decide. */
const WHY_YOURS: Record<Exclude<ChallengeDetail["decides_as"], "author">, string> = {
  lead: "yours to decide as a project lead",
  admin: "yours to decide as an admin",
  fallback: "nobody has decided in time, so anyone may",
  author_left: "its author has left the team, so anyone may",
};

function Proposal({
  challenge,
  who,
  marked,
  onDecide,
}: {
  challenge: ChallengeDetail;
  who: (memberId: string) => string;
  marked: boolean;
  onDecide: (challengeId: number, decision: "accept" | "reject") => void;
}) {
  const offered = challenge.challenger;
  const pieces = offered ? lineDiff(challenge.target.body, offered.body) : null;
  const changes = offered ? whatChanges(challenge.target.body, offered.body) : null;
  return (
    <div className="proposal">
      <p className="proposal-by">
        <IconScale size={14} stroke={1.6} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />
        <b>{who(challenge.raised_by)}</b> wants to {challenge.kind === "retire" ? "retire it" : "supersede it"} ·{" "}
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
                      changes from “{difference.from}” to “{difference.to}”
                    </>
                  ) : difference.kind === "added" ? (
                    <>is added: “{difference.to}”</>
                  ) : (
                    <>is dropped, where it now says “{difference.from}”</>
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
        <div>
          <Link className="title" to={memoryUrl(challenge.target.path)}>
            {challenge.target.title}
          </Link>
          <p className="by">As it stands now, by {who(challenge.target.author)}</p>
          <p className="body">{challenge.target.body}</p>
        </div>
        <div>
          {offered ? (
            <>
              <Link className="title" to={memoryUrl(offered.path)}>
                {offered.title}
              </Link>
              <p className="by">Offered in its place by {who(offered.author)}</p>
              <div className="body">
                {marked && pieces && changed(pieces) ? (
                  <Tracked pieces={pieces} testid="tracked" />
                ) : (
                  offered.body
                )}
              </div>
            </>
          ) : (
            <>
              <span className="title" style={{ color: "var(--ink-2)" }}>
                Nothing in its place
              </span>
              <p className="by">Asked for by {who(challenge.raised_by)}</p>
              <p className="body" style={{ color: "var(--ink-2)" }}>
                Retire it: {who(challenge.raised_by)} says it is no longer true.
              </p>
            </>
          )}
        </div>
      </div>
      <div className="decide">
        <Button size="sm" onClick={() => onDecide(challenge.challenge_id, "accept")} data-testid={`accept-${challenge.challenge_id}`}>
          {offered ? "Accept: supersede it" : "Accept: retire it"}
        </Button>
        <Button
          size="sm"
          variant="default"
          onClick={() => onDecide(challenge.challenge_id, "reject")}
          data-testid={`reject-${challenge.challenge_id}`}
        >
          Reject: keep it as it is
        </Button>
      </div>
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
                    <Link to={memoryUrl(one.target_path)} style={{ color: "inherit" }}>
                      {one.target_title}
                    </Link>
                  </td>
                  <td>
                    {one.kind === "retire" ? "to retire it" : "to supersede it"}
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
