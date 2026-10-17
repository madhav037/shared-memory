import { Button, TextInput } from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { searchEverywhere, type SearchHit } from "../api/client";
import { Dotted, Placeholder, Rank, Refusal, WaitingMark } from "../components/Bits";
import { useContents } from "../lib/contents";
import { memoryUrl, typeName, type Level, type MemoryType } from "../lib/format";
import { useAsked } from "../lib/useAsked";

// The filters name the server's levels and types in their own words, but they are the same words:
// these records are exhaustive over the vocabulary in lib/format, so a new level or type will not compile
// until it is named here too.
const LEVEL_FILTERS: Record<Level, string> = {
  project: "Project",
  team: "Team",
  personal: "Personal",
};

const TYPE_FILTERS: Record<MemoryType, string> = {
  convention: "Conventions",
  decision: "Decisions",
  architecture: "Architecture",
  gotcha: "Gotchas",
};

const options = (every: string, labels: Record<string, string>) => [
  { value: "", label: every },
  ...Object.entries(labels).map(([value, label]) => ({ value, label })),
];

const LEVELS = options("Every level", LEVEL_FILTERS);
const TYPES = options("Every type", TYPE_FILTERS);

/** Search every memory this member can reach, by meaning and by exact words, the way their coding agent does. */
export function SearchPage() {
  const [asked, setAsked] = useSearchParams();
  const query = asked.get("q") ?? "";
  const level = asked.get("level") ?? "";
  const type = asked.get("type") ?? "";
  const [typed, setTyped] = useState(query);

  useEffect(() => setTyped(query), [query]);

  const set = (name: string, value: string) => {
    const next = new URLSearchParams(asked);
    if (value) next.set(name, value);
    else next.delete(name);
    setAsked(next, { replace: name !== "q" });
  };

  return (
    <div className="column">
      <h1 className="page-title wide">Search</h1>
      <p className="standfirst">
        By meaning as well as exact words, across team memory and every project you can reach. Retired and superseded
        memory is left out, as it is for every coding agent.
      </p>

      <form
        role="search"
        className="form-line"
        style={{ marginTop: 24 }}
        onSubmit={(event) => {
          event.preventDefault();
          set("q", typed.trim());
        }}
      >
        <TextInput
          aria-label="What to look for"
          placeholder="e.g. which package manager do we use"
          value={typed}
          onChange={(event) => setTyped(event.currentTarget.value)}
          leftSection={<IconSearch size={16} stroke={1.6} aria-hidden />}
          size="md"
          style={{ flex: "1 1 320px" }}
          data-testid="search"
        />
        <Button type="submit" size="md" data-testid="search-go">
          Search
        </Button>
      </form>

      <div className="filters">
        <Filter label="Level" options={LEVELS} value={level} onChange={(value) => set("level", value)} testid="level" />
        <Filter label="Type" options={TYPES} value={type} onChange={(value) => set("type", value)} testid="type" />
      </div>

      {query ? <Results query={query} level={level} type={type} /> : <Hints />}
    </div>
  );
}

function Filter({
  label,
  options,
  value,
  onChange,
  testid,
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  testid: string;
}) {
  return (
    <div className="filter" role="group" aria-label={label} data-testid={testid}>
      <span>{label}</span>
      {options.map((option) => (
        <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Hints() {
  return (
    <p className="empty">
      Ask it the way you would ask a teammate: <b>“how do we deploy billing”</b>, <b>“staging database”</b>,{" "}
      <b>“why pnpm”</b>. It finds memories that mean the same thing even when the words differ.
    </p>
  );
}

function Results({ query, level, type }: { query: string; level: string; type: string }) {
  const { answer, refused } = useAsked(
    (signal) => searchEverywhere({ query, level: level || undefined, type: type || undefined, limit: 10 }, signal),
    [query, level, type],
  );

  if (refused) return <Refusal>{refused}</Refusal>;
  if (!answer) return <Placeholder lines={6} />;
  if (answer.results.length === 0)
    return (
      <p className="empty" data-testid="nothing-found">
        Nothing matches <b>“{query}”</b>
        {level || type ? " with those filters" : ""}. Try other words, or widen the filters.
      </p>
    );

  // One result per memory, strongest first. A memory has the words searched for if any section of it matched them.
  const unique = new Map<string, SearchHit>();
  for (const hit of answer.results) {
    const known = unique.get(hit.path);
    unique.set(hit.path, known ? { ...known, words_match: known.words_match || hit.words_match } : hit);
  }
  const hits = [...unique.values()];
  const worded = hits.filter((hit) => hit.words_match);
  const close = hits.filter((hit) => !hit.words_match);

  return (
    <div data-testid="results">
      <p className="history-stamp" role="status" data-testid="results-count">
        {strength(worded.length, close.length)}
      </p>
      {worded.length > 0 && <Entries hits={worded} query={query} testid="worded" />}
      {close.length > 0 && (
        <section className="weaker" aria-labelledby="weaker-heading" data-testid="weaker">
          {worded.length > 0 && (
            <>
              <h2 className="weaker-heading" id="weaker-heading">
                Weaker matches
              </h2>
              <p className="section-lede">Close in meaning, but without the words you searched for.</p>
            </>
          )}
          <Entries hits={close} query={query} testid="close" />
        </section>
      )}
    </div>
  );
}

/** How many results have the words searched for, and how many come only close in meaning. */
function strength(worded: number, close: number): string {
  const have = worded === 1 ? "One memory has" : `${worded} memories have`;
  if (close === 0) return `${have} the words you searched for${worded > 1 ? ", strongest first" : ""}.`;
  const more = close === 1 ? "one more comes" : `${close} more come`;
  if (worded > 0) return `${have} the words you searched for, and ${more} close in meaning.`;
  return close === 1
    ? "None has the words you searched for. This one comes closest in meaning."
    : `None has the words you searched for. These ${close} come closest in meaning, strongest first.`;
}

function Entries({ hits, query, testid }: { hits: SearchHit[]; query: string; testid: string }) {
  const { projects, nameOf } = useContents();
  const where = (hit: SearchHit) => projects.get(hit.project_id ?? "")?.name ?? hit.project_id ?? "";
  return (
    <ol className="entries" style={{ marginTop: 14 }} data-testid={testid}>
      {hits.map((hit) => (
        <li className={hit.level === "personal" ? "entry personal" : "entry"} key={hit.path}>
          <Link className="entry-title" to={memoryUrl(hit.path)}>
            <Marked text={hit.title} query={query} />
          </Link>
          {hit.heading !== hit.title && <p className="matched">Matched in “{hit.heading}”</p>}
          <p className="entry-summary">
            <Marked text={hit.summary} query={query} />
          </p>
          <Dotted className="entry-meta">
            {hit.level !== "team" && <span style={{ color: "var(--ink-2)", fontWeight: 600 }}>{where(hit)}</span>}
            <Rank level={hit.level} />
            <span>{typeName(hit.type)}</span>
            <span>by {nameOf(hit.author)}</span>
            {hit.level === "personal" && <span>not accepted by the team</span>}
            {hit.pending.length > 0 && <WaitingMark />}
          </Dotted>
        </li>
      ))}
    </ol>
  );
}

/** Words too common to be worth marking in a result. */
const COMMON = new Set(["the", "and", "for", "how", "what", "why", "who", "when", "where", "our", "does", "with", "this", "that"]);

/**
 * A result's words that the question used, marked as with a highlighter. Search goes by meaning, so a result can
 * match without sharing a word; then nothing is marked.
 */
function Marked({ text, query }: { text: string; query: string }) {
  const words = query
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((word) => word.length >= 3 && !COMMON.has(word));
  if (words.length === 0) return <>{text}</>;
  // The words are letters and digits only, so they need no escaping.
  const pattern = new RegExp(`(${words.join("|")})`, "giu");
  return (
    <>
      {text.split(pattern).map((part, place) =>
        place % 2 === 1 ? <mark key={place}>{part}</mark> : <span key={place}>{part}</span>,
      )}
    </>
  );
}
