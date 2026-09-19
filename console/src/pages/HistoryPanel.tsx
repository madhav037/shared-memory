import { Slider, Switch } from "@mantine/core";
import { IconArrowForwardUp } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import { fetchHistoryAt, fetchVersionAt, type MemoryVersion } from "../api/client";
import { changed, wordDiff } from "../lib/diff";
import { bodyOf, day, moment } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** What the header of a memory file says, line by line, so a change to its standing can be named. */
function headerOf(text: string): Map<string, string> {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const fields = new Map<string, string>();
  if (lines[0] !== "---") return fields;
  for (const line of lines.slice(1)) {
    if (line === "---") break;
    const at = line.indexOf(":");
    if (at > 0 && !line.startsWith(" ")) fields.set(line.slice(0, at), line.slice(at + 1).trim());
  }
  return fields;
}

const FIELD_NAMES: Record<string, string> = {
  status: "its status",
  superseded_by: "what superseded it",
  replaces: "what it replaces",
  exception_to: "the team memory it is an exception to",
  promoted_by: "who promoted it",
  title: "its title",
  summary: "its summary",
  type: "its type",
  related_files: "its related files",
};

export type History = {
  versions: MemoryVersion[];
  position: number;
  current: boolean;
  version: MemoryVersion | undefined;
  now: string | undefined;
  then: string | undefined;
  marked: boolean;
  setMarked: (marked: boolean) => void;
  moveTo: (position: number | null) => void;
};

/** A memory's versions, oldest first, and which one the page is showing. */
export function useHistory(path: string): History | null {
  const { answer } = useAsked((signal) => fetchHistoryAt(path, signal), [path]);
  const versions = useMemo(() => [...(answer?.versions ?? [])].reverse(), [answer]);
  const [at, setAt] = useState<number | null>(null);
  const [marked, setMarked] = useState(true);
  const [texts, setTexts] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    setAt(null);
    setTexts(new Map());
  }, [path]);

  const position = at ?? versions.length - 1;
  const version = versions[position];
  const before = versions[position - 1];
  const current = position === versions.length - 1;

  useEffect(() => {
    if (current) return;
    const wanted = [version, before].filter((one): one is MemoryVersion => Boolean(one) && !texts.has(one!.commit));
    if (wanted.length === 0) return;
    const attempt = new AbortController();
    Promise.all(wanted.map((one) => fetchVersionAt(path, one.commit, attempt.signal)))
      .then((found) =>
        setTexts((known) => {
          const next = new Map(known);
          found.forEach((one) => next.set(one.commit, one.text));
          return next;
        }),
      )
      .catch(() => undefined);
    return () => attempt.abort();
  }, [path, version, before, texts, current]);

  if (!answer) return null;
  return {
    versions,
    position,
    current,
    version,
    now: version ? texts.get(version.commit) : undefined,
    then: before ? texts.get(before.commit) : undefined,
    marked,
    setMarked,
    moveTo: setAt,
  };
}

/** The slider over a memory's versions, set right under its text so moving it changes what you read. */
export function Timeline({ history }: { history: History }) {
  if (history.versions.length < 2) return null;
  const last = history.versions.length - 1;
  return (
    <div className="timeline" data-testid="timeline">
      <span>{day(history.versions[0]?.at)}</span>
      <Slider
        min={0}
        max={last}
        step={1}
        value={history.position}
        onChange={(value) => history.moveTo(value === last ? null : value)}
        label={(value) => `${day(history.versions[value]?.at)} · ${history.versions[value]?.message ?? ""}`}
        marks={history.versions.map((_, place) => ({ value: place }))}
        size="sm"
        aria-label="Read it as it stood at"
        data-testid="history-slider"
        styles={{
          track: { "--slider-track-bg": "var(--rule)" } as React.CSSProperties,
          mark: { borderColor: "var(--rule)", background: "var(--paper)" },
        }}
      />
      <span>{history.current ? "Now" : `Version ${history.position + 1} of ${history.versions.length}`}</span>
    </div>
  );
}

/** Above the text while it shows an earlier version: when it stood like that, and the way back. */
export function AsItStood({ history }: { history: History }) {
  if (history.current || !history.version) return null;
  const { now, then } = history;
  const headerChanges =
    now !== undefined && then !== undefined
      ? [...new Set([...headerOf(then).keys(), ...headerOf(now).keys()])].filter(
          (key) => headerOf(then).get(key) !== headerOf(now).get(key),
        )
      : [];
  return (
    <div className="as-it-stood" data-testid="history-stamp" role="status">
      <span>
        As it stood on <b>{moment(history.version.at)}</b>, after “{history.version.message}” by {history.version.name}.
      </span>
      <button type="button" className="quiet-link" onClick={() => history.moveTo(null)} data-testid="back-to-now">
        <IconArrowForwardUp size={14} stroke={1.6} aria-hidden />
        Back to the current text
      </button>
      {history.position > 0 && (
        <Switch
          size="xs"
          label="Mark what this version changed"
          checked={history.marked}
          onChange={(event) => history.setMarked(event.currentTarget.checked)}
        />
      )}
      {history.marked && headerChanges.length > 0 && (
        <span className="note">This version also changed {headerChanges.map((key) => FIELD_NAMES[key] ?? key).join(", ")}.</span>
      )}
    </div>
  );
}

/** The memory's text as it stood at an earlier version, with what that version took out and put in marked. */
export function ThenText({ history }: { history: History }) {
  const { now, then, marked } = history;
  if (now === undefined) return <p className="then-text" aria-busy="true" style={{ color: "var(--ink-3)" }}>…</p>;
  const pieces = marked && then !== undefined ? wordDiff(bodyOf(then), bodyOf(now)) : null;
  return (
    <div className="then-text" data-testid="version-text" aria-live="polite">
      {pieces && changed(pieces)
        ? pieces.map((piece, place) =>
            piece.kind === "insert" ? (
              <ins key={place}>{piece.text}</ins>
            ) : piece.kind === "delete" ? (
              <del key={place}>{piece.text}</del>
            ) : (
              <span key={place}>{piece.text}</span>
            ),
          )
        : bodyOf(now)}
      {pieces && !changed(pieces) && <span className="unchanged">Its text didn’t change in this version.</span>}
    </div>
  );
}

/** Every version, newest first: the record, and a way to open any of them. */
export function HistoryLedger({ history, onPick }: { history: History; onPick: () => void }) {
  const newestFirst = [...history.versions].reverse();
  return (
    <section className="history" aria-labelledby="history-heading" id="history">
      <h2 className="section-heading" id="history-heading" style={{ marginTop: 0 }}>
        History
      </h2>
      <p className="section-lede">
        Every version of this memory, from the server’s record, back to when it was first written. Open one to read the
        memory as it stood then.
      </p>
      <table className="ledger" data-testid="versions">
        <caption className="visually-hidden">Every version, newest first</caption>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Who</th>
            <th scope="col">What happened</th>
          </tr>
        </thead>
        <tbody>
          {newestFirst.map((one) => {
            const place = history.versions.indexOf(one);
            const latest = place === history.versions.length - 1;
            return (
              <tr key={one.commit} aria-selected={place === history.position}>
                <td style={{ whiteSpace: "nowrap" }}>{moment(one.at)}</td>
                <td>{one.name}</td>
                <td>
                  <button
                    type="button"
                    onClick={() => {
                      history.moveTo(latest ? null : place);
                      onPick();
                    }}
                    data-testid="version-row"
                  >
                    {one.message}
                  </button>
                  {latest && <span style={{ color: "var(--ink-3)" }}> · current</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
