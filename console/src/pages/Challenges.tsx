import { Button, Switch } from "@mantine/core";
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
import { Placeholder, Rank, Refusal } from "../components/Bits";
import { useContents } from "../components/Contents";
import { changed, wordDiff } from "../lib/diff";
import { day, memoryUrl, moment } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** Everything disputed: what is waiting for this member's decision, and what they have asked of others. */
export function Challenges() {
  const { answer, refused, reload } = useAsked((signal) => fetchChallenges(signal), []);
  const { answer: team } = useAsked((signal) => fetchMembers(signal), []);
  const names = new Map((team?.members ?? []).map((one) => [one.employee_id, one.name]));
  const who = (employeeId: string) => (names.get(employeeId) ? `${names.get(employeeId)} (${employeeId})` : employeeId);

  return (
    <div className="medium">
      <h1 className="page-title wide">Challenges</h1>
      <p className="standfirst">
        A challenge asks a memory’s author to let it be superseded or retired. Its author decides; if they haven’t after a
        few days, or they have left the team, anyone can.
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
  who: (employeeId: string) => string;
  onDecided: () => void;
}) {
  const [refused, setRefused] = useState<string | null>(null);
  const [marked, setMarked] = useState(true);
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
      <Switch
        size="xs"
        label="Mark what each offer changes"
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

function Proposal({
  challenge,
  who,
  marked,
  onDecide,
}: {
  challenge: ChallengeDetail;
  who: (employeeId: string) => string;
  marked: boolean;
  onDecide: (challengeId: number, decision: "accept" | "reject") => void;
}) {
  const offered = challenge.challenger;
  const pieces = offered ? wordDiff(challenge.target.body, offered.body) : null;
  return (
    <div className="proposal">
      <p className="proposal-by">
        <IconScale size={14} stroke={1.6} aria-hidden style={{ verticalAlign: "-2px", marginRight: 6 }} />
        <b>{who(challenge.raised_by)}</b> wants to {challenge.kind === "retire" ? "retire it" : "supersede it"} ·{" "}
        {moment(challenge.raised_at)}
        {!challenge.yours && " · its author hasn’t decided in time, so anyone may"}
      </p>
      <div className="facing">
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
              <p className="body">
                {marked && pieces && changed(pieces)
                  ? pieces.map((piece, place) =>
                      piece.kind === "insert" ? (
                        <ins key={place}>{piece.text}</ins>
                      ) : piece.kind === "delete" ? (
                        <del key={place}>{piece.text}</del>
                      ) : (
                        <span key={place}>{piece.text}</span>
                      ),
                    )
                  : offered.body}
              </p>
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

function Raised({ raised, who }: { raised: RaisedChallenge[]; who: (employeeId: string) => string }) {
  return (
    <>
      <h2 className="section-heading">Challenges you raised</h2>
      {raised.length === 0 ? (
        <p className="empty">
          You haven’t raised any. A challenge is raised from Claude, when you promote a memory that should replace
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
                  <td style={{ whiteSpace: "nowrap" }}>{day(one.raised_at)}</td>
                  <td className="primary">
                    <Link to={memoryUrl(one.target_path)} style={{ color: "inherit" }}>
                      {one.target_title}
                    </Link>
                  </td>
                  <td>{one.kind === "retire" ? "to retire it" : "to supersede it"}</td>
                  <td>
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
