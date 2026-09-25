import { Slider } from "@mantine/core";
import { useEffect, useMemo, useState } from "react";

import { fetchHistoryAt, fetchVersionAt, type MemoryVersion } from "../api/client";
import { Amended } from "./Amended";
import { changed, wordDiff } from "../lib/diff";
import { bodyOf, day, headerOf, moment } from "../lib/format";
import { useAsked } from "../lib/useAsked";
import { inForce, whatHappened } from "../lib/versions";

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

/** Which parts of the header the version being read changed, in words. */
export function headerChanges(history: History): string[] {
  const { now, then } = history;
  if (now === undefined || then === undefined) return [];
  const was = headerOf(then);
  const is = headerOf(now);
  return [...new Set([...was.keys(), ...is.keys()])]
    .filter((key) => was.get(key) !== is.get(key))
    .map((key) => FIELD_NAMES[key] ?? key);
}

/** The point in time the memory is read at: from when it was first written to now, one stop per version. */
export function Timeline({ history, standing }: { history: History; standing: string }) {
  if (history.versions.length < 2) return null;
  const last = history.versions.length - 1;
  const cancelled = standing === "retired" || standing === "superseded";
  const ink = !history.current ? "var(--past)" : cancelled ? "var(--ink-3)" : "var(--accent)";
  return (
    <div className={history.current ? (cancelled ? "timeline cancelled" : "timeline") : "timeline past"} data-testid="timeline">
      <span className="timeline-end">
        First written
        <small>{day(history.versions[0]?.at)}</small>
      </span>
      <Slider
        min={0}
        max={last}
        step={1}
        value={history.position}
        onChange={(value) => history.moveTo(value === last ? null : value)}
        label={(value) => `Version ${value + 1} · ${day(history.versions[value]?.at)}`}
        marks={history.versions.map((_, place) => ({ value: place }))}
        size="sm"
        aria-label="Read it as it stood at"
        data-testid="history-slider"
        styles={{
          track: { "--slider-track-bg": "var(--rule)" } as React.CSSProperties,
          bar: { background: ink },
          thumb: { borderColor: ink, background: "var(--paper)" },
          mark: { borderColor: "var(--rule)", background: "var(--paper)" },
        }}
      />
      <span className="timeline-end now">
        {!history.current
          ? `Version ${history.position + 1} of ${history.versions.length}`
          : standing === "retired"
            ? "Retired"
            : standing === "superseded"
              ? "Superseded"
              : "Current"}
        <small>{history.current && !cancelled ? "as in force" : day(history.version?.at)}</small>
      </span>
    </div>
  );
}

/** The memory's text as it stood at an earlier version, with what that version put in and took out marked up. */
export function ThenText({ history }: { history: History }) {
  const { now, then, marked } = history;
  if (now === undefined)
    return (
      <p className="then-text" aria-busy="true" style={{ color: "var(--ink-3)" }}>
        …
      </p>
    );
  const pieces = marked && then !== undefined ? wordDiff(bodyOf(then), bodyOf(now)) : null;
  const source = history.version
    ? `version ${history.position + 1} (${history.version.name}, ${moment(history.version.at)})`
    : "this version";
  return (
    <div className="then-text" data-testid="version-text" aria-live="polite">
      {pieces && changed(pieces) ? (
        <Amended pieces={pieces} source={source} />
      ) : (
        <div className="amended">{bodyOf(now)}</div>
      )}
      {pieces && !changed(pieces) && <p className="unchanged">This version didn’t change its text.</p>}
    </div>
  );
}

/** Every version, newest first, in words: what it did, who did it, and when it was the text. */
export function HistoryLedger({
  history,
  title,
  standing,
  onPick,
}: {
  history: History;
  title: string;
  standing: string;
  onPick: () => void;
}) {
  const newestFirst = [...history.versions].reverse();
  return (
    <section className="history" aria-labelledby="history-heading" id="history">
      <h2 className="section-heading" id="history-heading">
        Versions
      </h2>
      <p className="section-lede">
        Every version of this memory from the server’s record, newest first. Open one to read the memory as it stood.
      </p>
      <ol className="versions" data-testid="versions" reversed>
        {newestFirst.map((one) => {
          const place = history.versions.indexOf(one);
          const latest = place === history.versions.length - 1;
          const reading = place === history.position;
          return (
            <li key={one.commit} aria-current={reading ? "true" : undefined}>
              <span className="version-number" aria-hidden>
                {place + 1}
              </span>
              <div>
                <p className="version-what">{whatHappened(one, title)}.</p>
                <p className="version-when">
                  {inForce(history.versions, place, standing)}.{" "}
                  {reading ? (
                    <span className="version-reading">{latest ? "The text above." : "You’re reading it."}</span>
                  ) : (
                    <button
                      type="button"
                      className="quiet-link"
                      onClick={() => {
                        history.moveTo(latest ? null : place);
                        onPick();
                      }}
                      data-testid="version-row"
                    >
                      {latest ? "Back to the current text" : `Read version ${place + 1}`}
                    </button>
                  )}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
