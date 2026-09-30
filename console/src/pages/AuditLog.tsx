import { Button, Select, TextInput } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { fetchAudit, type AuditEvent, type AuditFilters, type SignedInMember } from "../api/client";
import { Placeholder, Refusal } from "../components/Bits";
import { useContents } from "../lib/contents";
import { folderUrl, levelOf, memoryUrl, moment, typeName } from "../lib/format";
import { agentLabel } from "../lib/versions";

/** Every kind the server records, from the contract: the words below are exhaustive over it. */
type Kind = AuditEvent["kind"];

/** What each kind of change is called, in the order they are offered as a filter. */
const WORDS: Record<Kind, string> = {
  memory_saved: "Memory saved",
  memory_edited: "Memory edited",
  memory_deleted: "Memory deleted",
  memory_promoted: "Memory promoted",
  memory_superseded: "Memory superseded",
  memory_retired: "Memory retired",
  memory_pinned: "Memory pinned",
  memory_unpinned: "Memory unpinned",
  challenge_raised: "Challenge raised",
  challenge_decided: "Challenge decided",
  card_added: "Card added",
  card_edited: "Card edited",
  card_moved: "Card moved",
  card_claimed: "Card claimed",
  card_commented: "Card commented on",
  card_deleted: "Card deleted",
  card_returned: "Card returned to To do",
  signed_in: "Signed in",
  sign_in_refused: "Sign-in refused",
  token_issued: "Token issued",
  member_added: "Member added",
  member_removed: "Member removed",
  member_changed: "Member changed",
  admin_granted: "Admin granted",
  admin_revoked: "Admin taken away",
  ownership_handed_over: "Ownership handed over",
  project_created: "Project created",
  project_renamed: "Project renamed",
  lead_appointed: "Project lead appointed",
  lead_removed: "Project lead taken off",
  repository_added: "Repository added",
  repository_removed: "Repository forgotten",
  project_restricted: "Project restricted",
  project_opened: "Project opened to the team",
  access_granted: "Access granted",
  access_revoked: "Access taken away",
};

/** A memory file, named the way the contents name it, linked to where it can be read. */
function FileLink({ path }: { path: string }) {
  return (
    <Link to={memoryUrl(path)} title={path} className="path">
      {path.split("/").pop()}
    </Link>
  );
}

/** What else the record says about a change, in words rather than field names. */
function Details({ detail, nameOf }: { detail: Record<string, unknown>; nameOf: (memberId: string) => string }) {
  const text = (name: string) => {
    const value = detail[name];
    return value === null || value === undefined || value === "" ? null : String(value);
  };
  const said: React.ReactNode[] = [];
  const agent = text("agent");
  if (agent) said.push(agentLabel(agent));
  const level = text("level");
  const challenge = text("challenge");
  if (text("type")) said.push(text("type") === "architecture" ? "As architecture" : `As a ${typeName(text("type")!).toLowerCase()}`);
  if (text("was"))
    said.push(
      <span title={text("was")!}>
        From {levelOf(text("was")!)} memory
        {level ? ` into ${level} memory` : ""}
      </span>,
    );
  else if (level && !text("pinned")) said.push(`Into ${level} memory`);
  if (text("pinned")) said.push(text("pinned") === "topic" ? "A whole topic" : level ? `A ${level} memory` : "A memory");
  if (text("by"))
    said.push(
      <>
        Replaced by <FileLink path={text("by")!} />
      </>,
    );
  if (text("challenge_id"))
    said.push(
      `Challenge ${text("challenge_id")}${challenge ? `, to ${challenge === "retire" ? "retire it" : "supersede it"}` : ""}` +
        (text("decision") ? `: ${text("decision") === "accept" ? "accepted" : "rejected"}` : ""),
    );
  if (text("author")) said.push(`Its author, ${nameOf(text("author")!)}, decides`);
  if (text("name")) said.push(`Named ${text("name")}`);
  if (text("github")) said.push(`GitHub @${text("github")}`);
  if (text("for")) said.push(text("for") === "themselves" ? "Their own token" : `For ${nameOf(text("for")!)}`);
  if (text("reason")) said.push(text("reason"));
  return (
    <>
      {said.map((one, place) => (
        <span key={place}>
          {place > 0 ? " · " : ""}
          {one}
        </span>
      ))}
    </>
  );
}

/** Who changed what, and when: the team's register, newest first. */
export function AuditLog({ member }: { member: SignedInMember }) {
  const { projects, nameOf } = useContents();
  const [filters, setFilters] = useState<AuditFilters>({});
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const wholeTeam = member.role === "owner" || member.role === "admin";

  useEffect(() => {
    const attempt = new AbortController();
    setEvents(null);
    fetchAudit(filters, attempt.signal)
      .then((page) => {
        setEvents(page.events);
        setNext(page.next ?? null);
        setRefused(null);
      })
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, [filters]);

  const older = useCallback(async () => {
    if (next === null) return;
    const page = await fetchAudit({ ...filters, before: next });
    setEvents((seen) => [...(seen ?? []), ...page.events]);
    setNext(page.next ?? null);
  }, [filters, next]);

  const set = (name: keyof AuditFilters, value: string | null) =>
    setFilters((was) => ({ ...was, [name]: value || undefined }));
  const projectName = (id: string | null | undefined) => (id ? (projects.get(id)?.name ?? id) : "");

  return (
    <div>
      <h1 className="page-title wide">Audit log</h1>
      <p className="standfirst">
        {wholeTeam
          ? `Every change in team ${member.team}, newest first: members, roles, access, tokens and memory, from the console and from every coding agent.`
          : "Every change in the projects you lead, newest first."}{" "}
        What a memory said lives in its history; this records who changed it and when.
      </p>

      <div className="form-line" style={{ marginTop: 24 }}>
        <TextInput
          label="Member"
          placeholder="Member ID"
          data-testid="filter-member"
          onChange={(event) => set("member", event.currentTarget.value.trim())}
          style={{ flex: "1 1 140px" }}
        />
        <Select
          label="Change"
          placeholder="Every change"
          clearable
          searchable
          data={Object.entries(WORDS).map(([value, label]) => ({ value, label }))}
          data-testid="filter-kind"
          onChange={(value) => set("kind", value)}
          style={{ flex: "2 1 200px" }}
        />
        <Select
          label="Project"
          placeholder="Every project"
          clearable
          data={[...projects.values()].map((one) => ({ value: one.project_id, label: one.name }))}
          data-testid="filter-project"
          onChange={(value) => set("project", value)}
          style={{ flex: "2 1 180px" }}
        />
        <TextInput
          label="From"
          type="date"
          data-testid="filter-since"
          onChange={(event) => set("since", event.currentTarget.value)}
          style={{ flex: "1 1 140px" }}
        />
        <TextInput
          label="To"
          type="date"
          data-testid="filter-until"
          onChange={(event) => set("until", event.currentTarget.value)}
          style={{ flex: "1 1 140px" }}
        />
      </div>

      <div style={{ marginTop: 24 }}>
        {refused && <Refusal testid="audit-refused">{refused}</Refusal>}
        {!refused && events === null && <Placeholder lines={8} />}
        {!refused && events?.length === 0 && (
          <p className="empty" data-testid="audit-empty">
            Nothing matches those filters.
          </p>
        )}
        {!refused && events && events.length > 0 && (
          <div className="scroll-x">
            <table className="register" data-testid="audit-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Who</th>
                  <th scope="col">What</th>
                  <th scope="col">Where</th>
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => {
                  const isMemory = event.target?.endsWith(".md");
                  return (
                    <tr key={event.id}>
                      <td style={{ whiteSpace: "nowrap" }}>{moment(event.at)}</td>
                      <td className="primary who-cell" title={event.actor}>
                        {nameOf(event.actor)}
                      </td>
                      <td className="what-cell" style={{ color: "var(--ink)" }}>
                        {WORDS[event.kind]}
                      </td>
                      <td className="where-cell">
                        {projectName(event.project_id)}
                        {event.target && (
                          <div style={{ overflowWrap: "anywhere" }}>
                            {isMemory ? (
                              <FileLink path={event.target} />
                            ) : /^(team|projects)\//.test(event.target) ? (
                              <Link to={folderUrl(event.target)} title={event.target} className="path">
                                {event.target.split("/").pop()}/
                              </Link>
                            ) : event.kind.startsWith("repository_") ? (
                              <span className="path">{event.target}</span>
                            ) : (
                              nameOf(event.target)
                            )}
                          </div>
                        )}
                      </td>
                      <td style={{ fontSize: "0.8125rem" }}>
                        <Details detail={event.detail} nameOf={nameOf} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {next !== null && (
          <Button variant="default" mt="md" onClick={older} data-testid="audit-more">
            Show older
          </Button>
        )}
      </div>
    </div>
  );
}
