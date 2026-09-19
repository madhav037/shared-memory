import { Button, TextInput } from "@mantine/core";
import { IconBrandGithub, IconScale } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";

import { createProject, fetchChallenges, fetchFolder, signInUrl, type SignedInMember, type Status } from "../api/client";
import { Placeholder, Refusal, RestrictedMark } from "../components/Bits";
import { useContents } from "../components/Contents";
import { day, folderUrl, memoryUrl, plural } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** Before signing in: the title page of the team's code. */
export function TitlePage({ status, refused }: { status: Status; refused: string | null }) {
  return (
    <div className="title-page">
      <div className="title-page-inner">
        <h1>Shared Memory</h1>
        <p data-testid="status">
          The memory every Claude session on your team reads and writes. Connected to the server; sign in to read it.
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
            size="md"
            leftSection={<IconBrandGithub size={18} stroke={1.6} />}
            data-testid="sign-in"
          >
            Sign in with GitHub
          </Button>
        ) : (
          <p className="fine">Signing in with GitHub isn’t set up on this server yet. Whoever runs it sets the GitHub app’s details.</p>
        )}
        <p className="fine">Your personal token stays in Claude Code. The console never asks for it.</p>
      </div>
    </div>
  );
}

/** The front page: what is waiting for this member, then the contents of everything they can reach. */
export function Front({ member }: { member: SignedInMember }) {
  const { folders, projects, load } = useContents();
  const root = folders.get("");

  useEffect(() => {
    if (!root) load("");
  }, [root, load]);

  return (
    <div className="column">
      <h1 className="page-title">Contents</h1>
      <p className="standfirst">
        Everything the Claude sessions of team {member.team} read, set out folder by folder. Open a memory to read it
        exactly as Claude does, and to see who changed it and when.
      </p>

      <div style={{ marginTop: 32 }}>
        <Waiting />
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
                    <Link to={`/projects/${encodeURIComponent(project.project_id)}/settings`}>Settings</Link>
                  </p>
                )}
                {part.kind === "team" && <p className="toc-part-note">Holds for every project in the team.</p>}
                <PartContents path={part.path} kind={part.kind} />
              </li>
            );
          })}
        </ol>
      )}

      <NewProject />
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
        Nothing remembered yet. Connect a repository from its settings; memory arrives when a member’s Claude saves
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

/** Any member can start a project; they become its first project lead, as with create_project in Claude. */
function NewProject() {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
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
        }}
      >
        <TextInput
          label="Project name"
          placeholder="Billing"
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          data-testid="new-project-name"
          style={{ flex: "1 1 240px", maxWidth: 360 }}
        />
        <Button type="submit" loading={creating} disabled={!name.trim()} data-testid="create-project">
          Create project
        </Button>
      </form>
    </section>
  );
}
