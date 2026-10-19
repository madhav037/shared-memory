import { Button, TextInput } from "@mantine/core";
import { IconLock, IconLockOpen } from "@tabler/icons-react";
import { useState } from "react";
import { useParams } from "react-router";

import {
  addRepository,
  appointLead,
  assignKeeper,
  fetchMembers,
  fetchProject,
  grantAccess,
  removeKeeper,
  removeLead,
  removeRepository,
  renameProject,
  restrictProject,
  revokeAccess,
  type MemberSummary,
  type ProjectDetail,
  type SignedInMember,
} from "../api/client";
import { Placeholder, ProjectLinks, Refusal, RestrictedMark, Trail } from "../components/Bits";
import { AgentSelect, useChosenAgent } from "../components/AgentChoice";
import { ConnectionFiles } from "../components/ConnectionFiles";
import { MemberPicker } from "../components/MemberPicker";
import { useContents } from "../lib/contents";
import { useAsked } from "../lib/useAsked";

const FOUNDATION_NAMES: Record<string, string> = {
  architecture: "Architecture",
  product: "Product",
  glossary: "Glossary",
  decisions: "Decisions",
};

/** Who looks after a project, who can reach it, and the repositories that belong to it. */
export function ProjectSettings({ me }: { me: SignedInMember }) {
  const { projectId = "" } = useParams();
  const { answer: project, refused: notFound, setAnswer } = useAsked((signal) => fetchProject(projectId, signal), [projectId]);
  const [refused, setRefused] = useState<string | null>(null);
  const { refresh } = useContents();
  const { answer: team } = useAsked((signal) => fetchMembers(signal), []);
  const current = (team?.members ?? []).filter((one) => !one.removed);
  const [agent, setAgent] = useChosenAgent();

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
      <h1 className="page-title">Settings</h1>
      <p className="standfirst">
        Who looks after <b data-testid="project-name">{project.name}</b>, who can reach it, and its repositories. Its ID
        is <code data-testid="project-id">{project.project_id}</code>; every repository commits it to connect.
      </p>
      <div className="page-meta">
        {project.restricted ? <span data-testid="restricted"><RestrictedMark /></span> : <span>Open to the whole team</span>}
        {project.you_lead && (
          <span data-testid="you-lead">
            You lead this project
          </span>
        )}
        <ProjectLinks projectId={project.project_id} here="settings" />
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
        <p className="section-lede" data-testid="reach">
          {project.restricted
            ? "Restricted: only the members below, this project’s leads and the team’s admins can reach its memory — in the console and in every coding agent session."
            : project.access.length > 0
              ? `Every member of the team can reach its memory. Restricting it again lets the ${project.access.length === 1 ? "member" : `${project.access.length} members`} on its access list straight back in.`
              : "Every member of the team can reach its memory, in the console and in every coding agent session."}
        </p>
        {project.you_may_change && (
          <Button
            variant="default"
            leftSection={project.restricted ? <IconLockOpen size={16} stroke={1.6} /> : <IconLock size={16} stroke={1.6} />}
            onClick={() => attempt(() => restrictProject(project.project_id, !project.restricted))}
            data-testid="restrict"
          >
            {project.restricted ? "Open it to the whole team" : "Restrict it to its access list"}
          </Button>
        )}
        {project.restricted && (
          <>
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
                    {person.name}
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
              <Choosing
                members={current.filter((one) => !project.access.some((person) => person.member_id === one.member_id))}
                missing="Choose who to let in."
                action="Let them in"
                testid="access"
                onChosen={(memberId) => attempt(() => grantAccess(project.project_id, memberId))}
              />
            )}
          </>
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
                {lead.name}
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
          <Choosing
            members={current.filter((one) => !project.leads.some((lead) => lead.member_id === one.member_id))}
            missing="Choose who to appoint."
            action="Appoint as lead"
            testid="lead"
            onChosen={(memberId) => attempt(() => appointLead(project.project_id, memberId))}
          />
        )}
      </section>

      <section aria-labelledby="foundations-heading">
        <h2 className="section-heading" id="foundations-heading">
          Foundations
        </h2>
        <p className="section-lede">
          A foundation holds what everyone working on this project should know first. Its keepers decide the challenges
          to it alongside the project leads, and their own changes to it land at once.
        </p>
        {project.foundations.map((foundation) => (
          <div key={foundation.slug} data-testid={`foundation-${foundation.slug}`} style={{ marginTop: 18 }}>
            <h3 className="section-heading" style={{ fontSize: "1rem" }}>
              {FOUNDATION_NAMES[foundation.slug] ?? foundation.slug}
            </h3>
            <ul className="entries" data-testid={`keepers-${foundation.slug}`}>
              {foundation.keepers.length === 0 && (
                <li className="entry" style={{ color: "var(--ink-3)", fontSize: "0.9375rem" }}>
                  No keeper: the project’s leads decide.
                </li>
              )}
              {foundation.keepers.map((keeper) => (
                <li className="entry" key={keeper.member_id} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <span>{keeper.name}</span>
                  {project.you_may_change && (
                    <button
                      type="button"
                      className="quiet-link danger"
                      onClick={() => attempt(() => removeKeeper(project.project_id, foundation.slug, keeper.member_id))}
                      data-testid={`remove-keeper-${foundation.slug}-${keeper.member_id}`}
                    >
                      Take off
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {project.you_may_change && (
              <Choosing
                members={current.filter((one) => !foundation.keepers.some((keeper) => keeper.member_id === one.member_id))}
                missing="Choose who to assign."
                action="Assign as keeper"
                testid={`keeper-${foundation.slug}`}
                onChosen={(memberId) => attempt(() => assignKeeper(project.project_id, foundation.slug, memberId))}
              />
            )}
          </div>
        ))}
      </section>

      <section aria-labelledby="repositories-heading">
        <h2 className="section-heading" id="repositories-heading">
          Repositories
        </h2>
        <p className="section-lede">
          Each repository commits a few small files that connect it to this project, one set per coding agent your team
          uses. They name the project, never a token: each member sets theirs once in <code>SHARED_MEMORY_TOKEN</code>.
        </p>
        {project.repositories.length > 0 && <AgentSelect agent={agent} onChange={setAgent} />}
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
              <ConnectionFiles files={repository.files} agent={agent} testid={`files-${repository.name}`} />
            </div>
          ))}
        </div>
        {project.you_may_change && (
          <Adding
            label="Repository name"
            placeholder="e.g. billing-api"
            missing="Enter the repository’s name."
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
  const [tried, setTried] = useState(false);
  const missing = !asked.trim() ? "Enter the new name." : asked.trim() === name ? "That is already its name." : null;
  return (
    <section aria-labelledby="name-heading">
      <h2 className="section-heading" id="name-heading">
        Name
      </h2>
      <form
        className="form-line"
        onSubmit={(event) => {
          event.preventDefault();
          if (missing) setTried(true);
          else onRenamed(asked.trim());
        }}
      >
        <TextInput
          label="What the team calls it"
          value={asked}
          error={tried ? missing : undefined}
          data-testid="project-new-name"
          onChange={(event) => {
            setAsked(event.currentTarget.value);
            setTried(false);
          }}
          style={{ flex: "1 1 260px", maxWidth: 380 }}
        />
        <Button type="submit" variant="default" data-testid="rename-project">
          Rename
        </Button>
      </form>
    </section>
  );
}

/** Choose a member and send their member ID; sent with nobody chosen, it says so beside the field. */
function Choosing({
  members,
  missing,
  action,
  testid,
  onChosen,
}: {
  members: MemberSummary[];
  missing: string;
  action: string;
  testid: string;
  onChosen: (memberId: string) => void;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  return (
    <form
      className="form-line"
      style={{ marginTop: 14, borderTop: 0 }}
      onSubmit={(event) => {
        event.preventDefault();
        if (!chosen) return setTried(true);
        onChosen(chosen);
        setChosen(null);
        setTried(false);
      }}
    >
      <MemberPicker
        members={members}
        label="Member"
        placeholder="Search by name, member ID or GitHub"
        value={chosen}
        error={tried && !chosen ? missing : undefined}
        data-testid={`new-${testid}`}
        onChange={(memberId) => {
          setChosen(memberId);
          setTried(false);
        }}
        style={{ flex: "1 1 260px", maxWidth: 380 }}
      />
      <Button type="submit" variant="default" data-testid={`add-${testid}`}>
        {action}
      </Button>
    </form>
  );
}

function Adding({
  label,
  placeholder,
  missing,
  action,
  testid,
  onAdd,
}: {
  label: string;
  placeholder: string;
  /** What to say beside the field when it is sent empty. */
  missing: string;
  action: string;
  testid: string;
  onAdd: (value: string) => void;
}) {
  const [value, setValue] = useState("");
  const [tried, setTried] = useState(false);
  return (
    <form
      className="form-line"
      style={{ marginTop: 14, borderTop: 0 }}
      onSubmit={(event) => {
        event.preventDefault();
        if (!value.trim()) return setTried(true);
        onAdd(value.trim());
        setValue("");
        setTried(false);
      }}
    >
      <TextInput
        label={label}
        placeholder={placeholder}
        value={value}
        error={tried && !value.trim() ? missing : undefined}
        data-testid={`new-${testid}`}
        onChange={(event) => setValue(event.currentTarget.value)}
        style={{ flex: "1 1 200px", maxWidth: 300 }}
      />
      <Button type="submit" variant="default" data-testid={`add-${testid}`}>
        {action}
      </Button>
    </form>
  );
}
