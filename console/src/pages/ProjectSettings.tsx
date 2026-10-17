import { Button, TextInput } from "@mantine/core";
import { IconLock, IconLockOpen } from "@tabler/icons-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import {
  addRepository,
  appointLead,
  fetchProject,
  grantAccess,
  removeLead,
  removeRepository,
  renameProject,
  restrictProject,
  revokeAccess,
  type ProjectDetail,
  type SignedInMember,
} from "../api/client";
import { Placeholder, Refusal, RestrictedMark, Trail } from "../components/Bits";
import { ConnectionFiles } from "../components/ConnectionFiles";
import { boardUrl } from "../lib/board";
import { useContents } from "../lib/contents";
import { folderUrl } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** Who looks after a project, who can reach it, and the repositories that belong to it. */
export function ProjectSettings({ me }: { me: SignedInMember }) {
  const { projectId = "" } = useParams();
  const { answer: project, refused: notFound, setAnswer } = useAsked((signal) => fetchProject(projectId, signal), [projectId]);
  const [refused, setRefused] = useState<string | null>(null);
  const { refresh } = useContents();

  const attempt = async (what: () => Promise<ProjectDetail>) => {
    try {
      setAnswer(await what());
      setRefused(null);
      refresh();
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  if (notFound)
    return (
      <div className="narrow">
        <Trail steps={[]} />
        <Refusal>{notFound}</Refusal>
      </div>
    );
  if (!project) return <Placeholder lines={10} />;

  const runsTheTeam = me.role === "owner" || me.role === "admin";
  const home = `projects/${project.project_id}`;

  return (
    <div className="narrow">
      <Trail steps={[{ path: home, name: project.name }]} />
      <h1 className="page-title" data-testid="project-name">
        {project.name}
      </h1>
      <p className="standfirst">
        Settings for this project. Its ID is <code data-testid="project-id">{project.project_id}</code>; every repository
        commits it to connect.
      </p>
      <div className="page-meta">
        {project.restricted ? <span data-testid="restricted"><RestrictedMark /></span> : <span>Open to the whole team</span>}
        {project.you_lead && (
          <span className="mark strong" data-testid="you-lead">
            You lead this project
          </span>
        )}
        <Link to={folderUrl(home)} className="quiet-link">
          Browse its memory
        </Link>
        <Link to={boardUrl(project.project_id)} className="quiet-link">
          Its board
        </Link>
      </div>

      {!project.you_may_change && (
        <p className="empty" style={{ marginTop: 20 }} data-testid="read-only">
          Only this project’s leads and the team’s admins can change it. You can read everything here.
        </p>
      )}
      {refused && (
        <div style={{ marginTop: 20 }}>
          <Refusal testid="project-refused">{refused}</Refusal>
        </div>
      )}

      {project.you_may_change && (
        <Named name={project.name} onRenamed={(name) => attempt(() => renameProject(project.project_id, name))} />
      )}

      <section aria-labelledby="reach-heading">
        <h2 className="section-heading" id="reach-heading">
          Who can reach it
        </h2>
        <p className="section-lede">
          {project.restricted
            ? "Restricted: only the members below, this project’s leads and the team’s admins can reach its memory — in the console and in every coding agent session."
            : "Open to the whole team. Restricting it keeps its memory to the members below, its leads and the team’s admins."}
        </p>
        {project.you_may_change && (
          <Button
            variant={project.restricted ? "default" : "filled"}
            leftSection={project.restricted ? <IconLockOpen size={16} stroke={1.6} /> : <IconLock size={16} stroke={1.6} />}
            onClick={() => attempt(() => restrictProject(project.project_id, !project.restricted))}
            data-testid="restrict"
          >
            {project.restricted ? "Open it to the whole team" : "Restrict it to its access list"}
          </Button>
        )}
        <h3 className="sub-heading">Access list</h3>
        <ul className="entries" data-testid="access">
          {project.access.length === 0 && (
            <li className="entry" style={{ color: "var(--ink-3)", fontSize: "0.9375rem" }}>
              Nobody has been let in yet.
            </li>
          )}
          {project.access.map((person) => (
            <li className="entry" key={person.member_id} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span>
                {person.name} <span className="member-id">{person.member_id}</span>
              </span>
              {project.you_may_change && (
                <button
                  type="button"
                  className="quiet-link danger"
                  onClick={() => attempt(() => revokeAccess(project.project_id, person.member_id))}
                  data-testid={`revoke-${person.member_id}`}
                >
                  Take access away
                </button>
              )}
            </li>
          ))}
        </ul>
        {project.you_may_change && (
          <Adding
            label="Member ID"
            placeholder="E1042"
            action="Let them in"
            testid="access"
            onAdd={(memberId) => attempt(() => grantAccess(project.project_id, memberId))}
          />
        )}
        {!project.restricted && project.access.length > 0 && (
          <p className="section-lede" style={{ marginTop: 10 }}>
            The list is kept while the project is open, so restricting it again lets the same members straight back in.
          </p>
        )}
      </section>

      <section aria-labelledby="leads-heading">
        <h2 className="section-heading" id="leads-heading">
          Project leads
        </h2>
        <p className="section-lede">A project lead looks after this project: its access, its repositories and who else leads it.</p>
        <ul className="entries" data-testid="leads">
          {project.leads.length === 0 && (
            <li className="entry" style={{ color: "var(--ink-3)", fontSize: "0.9375rem" }}>
              Nobody leads this project.
            </li>
          )}
          {project.leads.map((lead) => (
            <li className="entry" key={lead.member_id} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span>
                {lead.name} <span className="member-id">{lead.member_id}</span>
              </span>
              {runsTheTeam && (
                <button
                  type="button"
                  className="quiet-link danger"
                  onClick={() => attempt(() => removeLead(project.project_id, lead.member_id))}
                  data-testid={`remove-lead-${lead.member_id}`}
                >
                  Take off
                </button>
              )}
            </li>
          ))}
        </ul>
        {project.you_may_change && (
          <Adding
            label="Member ID"
            placeholder="E1042"
            action="Appoint as lead"
            testid="lead"
            onAdd={(memberId) => attempt(() => appointLead(project.project_id, memberId))}
          />
        )}
      </section>

      <section aria-labelledby="repositories-heading">
        <h2 className="section-heading" id="repositories-heading">
          Repositories
        </h2>
        <p className="section-lede">
          Each repository commits a few small files that connect it to this project, one set per coding agent your team
          uses. They name the project, never a token: each member sets theirs once in <code>SHARED_MEMORY_TOKEN</code>.
        </p>
        <div data-testid="repositories">
          {project.repositories.length === 0 && (
            <p className="empty">No repositories yet. Add one to get the files it commits.</p>
          )}
          {project.repositories.map((repository) => (
            <div key={repository.name} className="entry">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
                <span className="entry-title" style={{ fontFamily: "var(--mono)", fontSize: "0.9375rem" }} data-testid={`repository-${repository.name}`}>
                  {repository.name}
                </span>
                <span style={{ display: "flex", gap: 14 }}>
                  {project.you_may_change && (
                    <button
                      type="button"
                      className="quiet-link danger"
                      onClick={() => attempt(() => removeRepository(project.project_id, repository.name))}
                      data-testid={`remove-repository-${repository.name}`}
                    >
                      Forget it
                    </button>
                  )}
                </span>
              </div>
              <ConnectionFiles files={repository.files} testid={`files-${repository.name}`} />
            </div>
          ))}
        </div>
        {project.you_may_change && (
          <Adding
            label="Repository name"
            placeholder="billing-api"
            action="Add repository"
            testid="repository"
            onAdd={(name) => attempt(() => addRepository(project.project_id, name))}
          />
        )}
      </section>
    </div>
  );
}

function Named({ name, onRenamed }: { name: string; onRenamed: (name: string) => void }) {
  const [asked, setAsked] = useState(name);
  return (
    <section aria-labelledby="name-heading">
      <h2 className="section-heading" id="name-heading">
        Name
      </h2>
      <form
        className="form-line"
        onSubmit={(event) => {
          event.preventDefault();
          if (asked.trim() && asked !== name) onRenamed(asked.trim());
        }}
      >
        <TextInput
          label="What the team calls it"
          value={asked}
          data-testid="project-new-name"
          onChange={(event) => setAsked(event.currentTarget.value)}
          style={{ flex: "1 1 260px", maxWidth: 380 }}
        />
        <Button type="submit" variant="default" disabled={!asked.trim() || asked === name} data-testid="rename-project">
          Rename
        </Button>
      </form>
    </section>
  );
}

function Adding({
  label,
  placeholder,
  action,
  testid,
  onAdd,
}: {
  label: string;
  placeholder: string;
  action: string;
  testid: string;
  onAdd: (value: string) => void;
}) {
  const [value, setValue] = useState("");
  return (
    <form
      className="form-line"
      style={{ marginTop: 14, borderTop: 0 }}
      onSubmit={(event) => {
        event.preventDefault();
        if (!value.trim()) return;
        onAdd(value.trim());
        setValue("");
      }}
    >
      <TextInput
        label={label}
        placeholder={placeholder}
        value={value}
        data-testid={`new-${testid}`}
        onChange={(event) => setValue(event.currentTarget.value)}
        style={{ flex: "1 1 200px", maxWidth: 300 }}
      />
      <Button type="submit" variant="default" disabled={!value.trim()} data-testid={`add-${testid}`}>
        {action}
      </Button>
    </form>
  );
}
