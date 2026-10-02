import { Button } from "@mantine/core";
import { IconLayoutColumns, IconPin, IconPinnedOff, IconSettings, IconTerminal2 } from "@tabler/icons-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { fetchFolder, fetchPins, pinAt, unpinAt, type FileEntry, type SignedInMember } from "../api/client";
import { ChallengedMark, OutdatedMark, PinnedMark, Placeholder, Rank, Refusal, RestrictedMark, Trail } from "../components/Bits";
import { boardUrl } from "../lib/board";
import { useContents } from "../lib/contents";
import { day, folderUrl, memoryUrl, plural, sessionsUrl, typeName } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** What each folder holds, in the words CONTEXT.md defines them with. */
const MEANING: Record<string, string> = {
  team: "Memory that holds for every project in the team.",
  shared: "Memory that holds for everyone working on this project.",
  people: "Each member’s personal memory in this project: readable by the team, but not accepted by it.",
  member: "Personal memory: readable by the team, but not accepted by it.",
  Conventions: "Rules for how the team works, followed every day.",
  Decisions: "Choices made once, recorded with their reasons and the alternatives rejected.",
  Architecture: "How the system is built and how its parts relate.",
  Gotchas: "Surprising facts that waste time if you don’t know them.",
  topic: "A topic: several memories on one subject too long for one memory.",
};

const TEACHING: Record<string, string> = {
  team: "Team memory holds for every project. It arrives here when a member promotes one of their memories to team memory.",
  project: "This project has no memory yet. Connect a repository from its settings; memory arrives when a member’s coding agent saves something there.",
  shared: "Project memory is what everyone on this project follows. It arrives when a member promotes one of their memories.",
  people: "Personal memory is what each member’s coding agent has saved in this project. Nobody has saved anything here yet.",
};

/** One folder, set out as a part of the contents: every folder beneath it, and every memory in each. */
export function FolderPage({ member }: { member: SignedInMember }) {
  const [asked] = useSearchParams();
  const path = asked.get("folder") ?? "";
  const { answer: folder, refused, reload } = useAsked((signal) => fetchFolder(path, signal, true), [path]);
  const { projects, refresh } = useContents();
  const [pinRefused, setPinRefused] = useState<string | null>(null);

  if (refused)
    return (
      <div className="column">
        <Trail steps={[]} />
        <Refusal testid="folder-refused">{refused}</Refusal>
      </div>
    );
  if (!folder) return <Placeholder lines={10} />;

  const projectId = path.startsWith("projects/") ? path.split("/")[1] : undefined;
  const project = projectId ? projects.get(projectId) : undefined;
  const total = folder.memories.length + folder.inside.reduce((sum, section) => sum + section.memories.length, 0);
  const meaning = MEANING[folder.kind === "type" ? folder.name : folder.kind];

  const pinTopic = async (pin: boolean) => {
    try {
      await (pin ? pinAt : unpinAt)(path);
      setPinRefused(null);
      refresh();
      reload();
    } catch (problem) {
      setPinRefused((problem as Error).message);
    }
  };

  return (
    <div className="column" data-testid="folder">
      <Trail steps={folder.trail} />
      <h1 className="page-title" data-testid="folder-name">
        {folder.name}
      </h1>
      {folder.kind === "project" && project ? (
        <p className="standfirst">
          {project.leads.length === 0 ? "No project lead yet." : `Led by ${project.leads.map((lead) => lead.name).join(", ")}.`}{" "}
          {project.restricted ? "Restricted to its access list." : "Open to the whole team."}
        </p>
      ) : (
        meaning && <p className="standfirst">{meaning}</p>
      )}
      <div className="page-meta">
        <span>
          <b>{plural(total, "memory", "memories")}</b>
          {folder.inside.length > 0 ? ` in ${plural(folder.inside.length, "folder")}` : ""}
        </span>
        {project?.restricted && <RestrictedMark />}
        {folder.kind === "project" && projectId && (
          <Link to={boardUrl(projectId)} className="quiet-link" data-testid="to-board">
            <IconLayoutColumns size={14} stroke={1.6} aria-hidden />
            Board
          </Link>
        )}
        {folder.kind === "project" && projectId && (
          <Link to={sessionsUrl(projectId)} className="quiet-link" data-testid="to-sessions">
            <IconTerminal2 size={14} stroke={1.6} aria-hidden />
            Sessions
          </Link>
        )}
        {folder.kind === "project" && projectId && (
          <Link to={`/projects/${encodeURIComponent(projectId)}/settings`} className="quiet-link">
            <IconSettings size={14} stroke={1.6} aria-hidden />
            Project settings
          </Link>
        )}
        {folder.pinned && <PinnedMark />}
        {folder.pinnable &&
          (folder.pinned ? (
            <button type="button" className="quiet-link" onClick={() => pinTopic(false)} data-testid="unpin-topic">
              <IconPinnedOff size={14} stroke={1.6} aria-hidden />
              Unpin this topic
            </button>
          ) : (
            <button type="button" className="quiet-link" onClick={() => pinTopic(true)} data-testid="pin-topic">
              <IconPin size={14} stroke={1.6} aria-hidden />
              Pin this topic into every briefing
            </button>
          ))}
      </div>
      {pinRefused && (
        <div style={{ marginTop: 16 }}>
          <Refusal testid="pin-refused">{pinRefused}</Refusal>
        </div>
      )}

      {folder.kind === "project" && projectId && <Briefing projectId={projectId} />}

      {total === 0 ? (
        <>
          <p className="empty" data-testid="empty" style={{ marginTop: 28 }}>
            {TEACHING[folder.kind] ?? "Nothing has been remembered in this folder yet."}
          </p>
          {folder.kind === "project" && projectId && (
            <p style={{ marginTop: 20 }}>
              <Button component={Link} to={`/projects/${encodeURIComponent(projectId)}/settings`} variant="default">
                Connect a repository
              </Button>
            </p>
          )}
        </>
      ) : (
        <div className="part-contents" data-testid="tree">
          {folder.memories.length > 0 && <Lines memories={folder.memories} me={member} depth={1} />}
          {folder.inside.map((section) => (
            <section key={section.path} aria-label={section.name} style={{ "--depth": section.depth } as React.CSSProperties}>
              <Link
                className={section.depth > 1 ? "part-head deep" : "part-head"}
                to={folderUrl(section.path)}
                data-testid="subfolder"
              >
                <span className="name">{section.name}</span>
                <span className="leader" aria-hidden />
                <span className="figures">
                  {plural(section.count, "memory", "memories")}
                  {section.changed ? ` · ${day(section.changed)}` : ""}
                </span>
              </Link>
              {section.memories.length > 0 && <Lines memories={section.memories} me={member} depth={section.depth} />}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

/** The memories of one folder, current first, then what is no longer current, struck through in its place. */
function Lines({ memories, me, depth }: { memories: FileEntry[]; me: SignedInMember; depth: number }) {
  const ordered = [
    ...memories.filter((memory) => memory.status === "active"),
    ...memories.filter((memory) => memory.status !== "active"),
  ];
  return (
    <ul style={{ margin: 0, padding: 0, "--depth": depth } as React.CSSProperties}>
      {ordered.map((memory) => (
        <Line key={memory.path} memory={memory} me={me} />
      ))}
    </ul>
  );
}

function Line({ memory, me }: { memory: FileEntry; me: SignedInMember }) {
  const cancelled = memory.status !== "active";
  const classes = ["line", memory.level === "personal" ? "personal" : "", cancelled ? "cancelled" : ""].join(" ");
  return (
    <li className={classes}>
      <div className="line-top">
        <Link className="line-title" to={memoryUrl(memory.path)}>
          {memory.status === "superseded" && (
            <span className="dagger" aria-hidden>
              †{" "}
            </span>
          )}
          {memory.title}
        </Link>
        {(memory.pinned || memory.challenged > 0 || memory.possibly_outdated) && (
          <span className="line-marks">
            {memory.pinned && <PinnedMark />}
            {memory.challenged > 0 && <ChallengedMark count={memory.challenged} />}
            {memory.possibly_outdated && <OutdatedMark />}
          </span>
        )}
        <span className="leader" aria-hidden />
        <span className="line-figures">
          <span>{typeName(memory.type)}</span>
          <span>{memory.author === me.member_id ? "you" : memory.author_name}</span>
          {memory.changed && <span>{day(memory.changed)}</span>}
        </span>
      </div>
      <p className="line-summary">
        {cancelled && <b style={{ fontWeight: 600 }}>{memory.status === "superseded" ? "Superseded. " : "Retired. "}</b>}
        {memory.waiting && <b style={{ fontWeight: 600 }}>Waiting on a challenge. </b>}
        {memory.summary}
      </p>
    </li>
  );
}

/** What every session in this project is briefed with, and how much of the briefing's room it takes. */
function Briefing({ projectId }: { projectId: string }) {
  const { answer, refused, reload } = useAsked((signal) => fetchPins(projectId, signal), [projectId]);
  const { refresh, nameOf } = useContents();
  const [unpinRefused, setUnpinRefused] = useState<string | null>(null);

  if (refused) return <Refusal>{refused}</Refusal>;
  if (!answer) return null;

  return (
    <section aria-labelledby="briefing-heading" data-testid="pins">
      <h2 className="sub-heading" id="briefing-heading">
        In every briefing
      </h2>
      {answer.pins.length === 0 ? (
        <p className="empty">
          Nothing is pinned. Pin a project or team memory, or a topic, from its page, and every session in this project
          starts with it.
        </p>
      ) : (
        <>
          <p className="section-lede" style={{ marginBottom: 8 }}>
            Every session in this project starts with these, in this order. They take about{" "}
            <b style={{ color: "var(--ink)" }}>{answer.tokens.toLocaleString()}</b> of the briefing’s{" "}
            {answer.cap.toLocaleString()} tokens.
          </p>
          {unpinRefused && <Refusal>{unpinRefused}</Refusal>}
          <ul className="entries">
            {answer.pins.map((one) => (
              <li className="entry" key={one.path} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                <span>
                  {one.kind === "memory" ? (
                    <Link className="entry-title" to={memoryUrl(one.path)}>
                      {one.title}
                    </Link>
                  ) : (
                    <Link className="entry-title" to={folderUrl(one.path)}>
                      {one.title} <span style={{ fontWeight: 400, color: "var(--ink-3)" }}>(topic)</span>
                    </Link>
                  )}
                  <span className="entry-meta" style={{ marginTop: 4 }}>
                    <Rank level={one.level} />
                    <span>about {one.tokens.toLocaleString()} tokens</span>
                    <span>pinned by {nameOf(one.pinned_by)}</span>
                  </span>
                </span>
                <button
                  type="button"
                  className="quiet-link"
                  data-testid={`unpin-${one.kind}`}
                  onClick={async () => {
                    try {
                      await unpinAt(one.path);
                      setUnpinRefused(null);
                      refresh();
                      reload();
                    } catch (problem) {
                      setUnpinRefused((problem as Error).message);
                    }
                  }}
                >
                  Unpin
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
