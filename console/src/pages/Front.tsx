import { Button, TextInput } from "@mantine/core";
import { IconArrowRight, IconBell, IconBrandGithub, IconScale } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";

import {
  createProject,
  fetchChallenges,
  fetchFolder,
  fetchNotices,
  signInUrl,
  type SignedInMember,
  type Status,
} from "../api/client";
import { Placeholder, Refusal, RestrictedMark } from "../components/Bits";
import { boardUrl } from "../lib/board";
import { useContents } from "../lib/contents";
import { day, folderUrl, longDay, memoryUrl, moment, plural, readableNotice } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** Before signing in: the title page of the team's memory, and what the console is for. */
export function TitlePage({ status, refused }: { status: Status; refused: string | null }) {
  return (
    <div className="title-page">
      <div className="title-page-inner">
        <h1>Shared Memory</h1>
        <p className="long-title">
          The memory every coding agent on your team reads and writes, so that what one member’s agent learns
          reaches every other member’s agent.
        </p>
        {refused && (
          <Refusal testid="sign-in-error">
            <b>That sign-in didn’t work.</b> {refused}
          </Refusal>
        )}
        {status.github_sign_in ? (
          <Button
            component="a"
            href={signInUrl}
            size="lg"
            leftSection={<IconBrandGithub size={20} stroke={1.6} />}
            rightSection={<IconArrowRight size={18} stroke={2} />}
            data-testid="sign-in"
          >
            Sign in with GitHub
          </Button>
        ) : (
          <p className="fine">Signing in with GitHub isn’t set up on this server yet. Whoever runs it sets the GitHub app’s details.</p>
        )}
        <p className="fine" data-testid="status">Connected to the server. Your personal token stays with your coding agent; the console never asks for it.</p>
        <ul className="title-page-uses">
          <li>
            <b>Read it as your agent does.</b> Every memory your team and your projects hold, word for word.
          </li>
          <li>
            <b>See how it came to say that.</b> Every version, who made it and when, with each amendment marked.
          </li>
          <li>
            <b>Decide what stands.</b> Challenges waiting for you, side by side with what is offered in their place.
          </li>
        </ul>
      </div>
    </div>
  );
}

/** The front page: what is waiting for this member, then the contents of everything they can reach. */
export function Front({ member }: { member: SignedInMember }) {
  const { folders, projects, load } = useContents();
  const root = folders.get("");
  const newest = root?.folders
    .map((folder) => folder.changed)
    .filter((changed): changed is string => Boolean(changed))
    .sort()
    .pop();

  useEffect(() => {
    if (!root) load("");
  }, [root, load]);

  return (
    <div className="column">
      <h1 className="page-title">Contents</h1>
      {newest && (
        <p className="currency" data-testid="current-to">
          <span>Current to {longDay(newest)}</span>
        </p>
      )}
      <p className="standfirst">
        Everything the coding agents of team {member.team} read, set out folder by folder. Open a memory to read it
        exactly as they do, and to see who changed it and when.
      </p>

      <div style={{ marginTop: 32 }}>
        <Waiting />
        <Told />
      </div>

      {!root ? (
        <Placeholder lines={8} />
      ) : (
        <ol className="toc" data-testid="projects">
          {root.folders.map((part) => {
            const project = part.kind === "project" ? projects.get(part.path.split("/")[1]!) : undefined;
            return (
              <li className="toc-part" key={part.path} data-testid="project-card">
                <Link className="toc-line part" to={folderUrl(part.path)}>
                  <span className="name">
                    <span>{part.name}</span>
                    {project?.restricted && <RestrictedMark />}
                  </span>
                  <span className="leader" aria-hidden />
                  <span className="figures">
                    {plural(part.memories, "memory", "memories")}
                    {part.changed ? ` · ${day(part.changed)}` : ""}
                  </span>
                </Link>
                {project && (
                  <p className="toc-part-note" data-testid={`leads-${project.project_id}`}>
                    {project.leads.length === 0
                      ? "No project lead."
                      : `Led by ${project.leads.map((lead) => lead.name).join(", ")}.`}
                    {project.you_lead ? " You lead this." : ""}{" "}
                    <Link to={boardUrl(project.project_id)}>Board</Link>
                    {"\u00a0·\u00a0"}
                    <Link to={`/projects/${encodeURIComponent(project.project_id)}/settings`}>Settings</Link>
                  </p>
                )}
                {part.kind === "team" && (
                  <p className="toc-part-note" data-testid="team-note">
                    Holds for every project in the team.
                    {part.memories === 0 &&
                      " It arrives when a member’s coding agent promotes a memory in a session; the console never writes it."}
                  </p>
                )}
                <PartContents path={part.path} kind={part.kind} />
              </li>
            );
          })}
        </ol>
      )}

      <NewProject />

      <footer className="colophon">
        <p>
          Kept by the Shared Memory server in a git repository. Memory the team has accepted is never deleted: it is
          superseded or retired, and every version stays in its history.
        </p>
        <p>Set in Cooper Hewitt, Charis SIL and Source Code Pro.</p>
      </footer>
    </div>
  );
}

/** The folders of one part, two levels down: project memory and people, then the types and members within them. */
function PartContents({ path, kind }: { path: string; kind: string }) {
  const { answer } = useAsked((signal) => fetchFolder(path, signal, true), [path]);
  if (!answer) return null;
  const sections = answer.inside.filter((section) => section.depth <= 2);
  if (sections.length === 0)
    return kind === "project" ? (
      <p className="toc-part-note">
        Nothing remembered yet. Connect a repository from its settings; memory arrives when a member’s coding agent saves
        something.
      </p>
    ) : null;
  return (
    <ul className="toc-sub">
      {sections.map((section) => (
        <li key={section.path} className={section.depth > 1 ? "deeper" : undefined}>
          <Link className="toc-line" to={folderUrl(section.path)}>
            <span className="name">
              <span>{section.name}</span>
            </span>
            <span className="leader" aria-hidden />
            <span className="figures">
              {section.count}
              {section.changed ? ` · ${day(section.changed)}` : ""}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Challenges waiting for this member, set off as a notice at the front. */
function Waiting() {
  const { answer } = useAsked((signal) => fetchChallenges(signal), []);
  const { nameOf } = useContents();
  if (!answer || answer.waiting.length === 0) return null;
  const count = answer.waiting.length;
  return (
    <section className="notice appear" aria-labelledby="waiting-heading" data-testid="waiting">
      <h2 className="notice-title" id="waiting-heading">
        <IconScale size={17} stroke={1.6} aria-hidden />
        {count === 1 ? "A challenge is waiting for your decision" : `${count} challenges are waiting for your decision`}
      </h2>
      <ol>
        {answer.waiting.map((challenge) => (
          <li key={challenge.challenge_id}>
            <Link to={memoryUrl(challenge.target.path)}>{challenge.target.title}</Link>
            <span>
              {nameOf(challenge.raised_by)} wants to {challenge.kind === "retire" ? "retire it" : "supersede it"}
              {challenge.challenger ? ` with “${challenge.challenger.title}”` : ""}
            </span>
          </li>
        ))}
      </ol>
      <p style={{ margin: "10px 0 0", fontSize: "0.875rem" }}>
        <Link to="/challenges" data-testid="decide-them">
          Compare and decide
        </Link>
      </p>
    </section>
  );
}

/**
 * What this member has been told about their cards and challenges: the notices their coding agent passes on in a
 * briefing, here for a member who isn't in a session. Reading them here leaves them waiting for that briefing.
 */
function Told() {
  const { answer } = useAsked((signal) => fetchNotices(signal), []);
  const { nameOf, projects } = useContents();
  if (!answer || answer.notices.length === 0) return null;
  const known = (memberId: string) => (nameOf(memberId) === memberId ? undefined : nameOf(memberId));
  const projectNames = [...projects].map(([projectId, project]): [string, string] => [projectId, project.name]);
  const count = answer.notices.length;
  return (
    <section className="notice told appear" aria-labelledby="told-heading" data-testid="notices">
      <h2 className="notice-title" id="told-heading">
        <IconBell size={17} stroke={1.6} aria-hidden />
        {count === 1 ? "A notice for you" : `${count} notices for you`}
      </h2>
      <ol>
        {answer.notices.map((notice) => (
          <li key={notice.notice_id} data-testid="notice">
            <span className="notice-text">{readableNotice(notice.text, known, projectNames)}</span>
            <span className="notice-when">
              {moment(notice.created_at)}
              {notice.project_id && (
                <>
                  {"\u00a0·\u00a0"}
                  <Link
                    className="quiet-link"
                    to={boardUrl(notice.project_id, { card: notice.card ?? undefined })}
                    data-testid="notice-link"
                  >
                    {notice.card === null ? "Open the board" : `Open card ${notice.card}`}
                  </Link>
                </>
              )}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Any member can start a project; they become its first project lead, as with create_project from a coding agent. */
function NewProject() {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const { refresh } = useContents();
  const goTo = useNavigate();

  const create = async () => {
    setCreating(true);
    try {
      const project = await createProject(name.trim());
      refresh();
      goTo(`/projects/${encodeURIComponent(project.project_id)}/settings`);
    } catch (problem) {
      setRefused((problem as Error).message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <section style={{ marginTop: 48 }} aria-labelledby="new-project-heading">
      <h2 className="section-heading" id="new-project-heading">
        Start a project
      </h2>
      <p className="section-lede">
        A project holds the memory for one product. You become its first project lead, and connect its repositories from
        its settings.
      </p>
      {refused && <Refusal testid="new-project-refused">{refused}</Refusal>}
      <form
        className="form-line"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) void create();
          else setMissing(true);
        }}
      >
        <TextInput
          label="Project name"
          placeholder="e.g. Payments"
          value={name}
          error={missing && !name.trim() ? "Enter the project’s name." : undefined}
          onChange={(event) => setName(event.currentTarget.value)}
          data-testid="new-project-name"
          style={{ flex: "1 1 240px", maxWidth: 360 }}
        />
        <Button type="submit" loading={creating} data-testid="create-project">
          Create project
        </Button>
      </form>
    </section>
  );
}
