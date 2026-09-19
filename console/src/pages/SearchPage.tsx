import { Button, TextInput } from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { searchEverywhere, type SearchHit } from "../api/client";
import { Placeholder, Rank, Refusal, WaitingMark } from "../components/Bits";
import { useContents } from "../components/Contents";
import { memoryUrl, typeName } from "../lib/format";
import { useAsked } from "../lib/useAsked";

const LEVELS = [
  { value: "", label: "Every level" },
  { value: "project", label: "Project" },
  { value: "team", label: "Team" },
  { value: "personal", label: "Personal" },
];

const TYPES = [
  { value: "", label: "Every type" },
  { value: "convention", label: "Conventions" },
  { value: "decision", label: "Decisions" },
  { value: "architecture", label: "Architecture" },
  { value: "gotcha", label: "Gotchas" },
];

/** Search every memory this member can reach, by meaning and by exact words, the way their Claude does. */
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
        memory is left out, as it is for Claude.
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
          placeholder="which package manager do we use"
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
  const { projects, nameOf } = useContents();
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

  // One result per memory, strongest first, each saying where it lives.
  const seen = new Set<string>();
  const unique = answer.results.filter((hit) => (seen.has(hit.path) ? false : (seen.add(hit.path), true)));
  const where = (hit: SearchHit) => projects.get(hit.project_id ?? "")?.name ?? hit.project_id ?? "";

  return (
    <div data-testid="results">
      <p className="history-stamp" role="status">
        {unique.length === 1 ? "One memory matches, strongest first." : `The ${unique.length} closest memories, strongest first.`}
      </p>
      <ol className="entries" style={{ marginTop: 14 }}>
        {unique.map((hit) => (
          <li className={hit.level === "personal" ? "entry personal" : "entry"} key={hit.path}>
            <Link className="entry-title" to={memoryUrl(hit.path)}>
              <Marked text={hit.title} query={query} />
            </Link>
            {hit.heading !== hit.title && <p className="matched">Matched in “{hit.heading}”</p>}
            <p className="entry-summary">
              <Marked text={hit.summary} query={query} />
            </p>
            <div className="entry-meta">
              {hit.level !== "team" && <span style={{ color: "var(--ink-2)", fontWeight: 600 }}>{where(hit)}</span>}
              <Rank level={hit.level} />
              <span>{typeName(hit.type)}</span>
              <span>by {nameOf(hit.author)}</span>
              {hit.level === "personal" && <span>not accepted by the team</span>}
              {hit.pending.length > 0 && <WaitingMark />}
            </div>
          </li>
        ))}
      </ol>
    </div>
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
