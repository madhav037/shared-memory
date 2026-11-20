import { Button, Select, TextInput } from "@mantine/core";
import { useState } from "react";
import { Link } from "react-router";

import {
  appointDepartmentLead,
  createDepartment,
  fetchDepartments,
  fetchMembers,
  moveProjectIn,
  moveProjectOut,
  removeDepartment,
  removeDepartmentLead,
  renameDepartment,
  type Departments as DepartmentList,
  type DepartmentSummary,
  type MemberSummary,
  type ProjectSummary,
} from "../api/client";
import { Placeholder, Refusal, Trail } from "../components/Bits";
import { folderUrl } from "../lib/format";
import { useContents } from "../lib/contents";
import { useAsked } from "../lib/useAsked";
import { Adding, Choosing } from "./ProjectSettings";

/** The company's departments (ADR-0032): what each is called, who leads it, and which projects are in it. */
export function Departments() {
  const { answer, refused: notFound, setAnswer } = useAsked((signal) => fetchDepartments(signal), []);
  const { answer: company } = useAsked((signal) => fetchMembers(signal), []);
  const { projects, refresh } = useContents();
  const [refused, setRefused] = useState<string | null>(null);
  const current = (company?.members ?? []).filter((one) => !one.removed);
  const inNone = [...projects.values()].filter((one) => one.department === null);

  const attempt = async (what: () => Promise<DepartmentList>) => {
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
  if (!answer) return <Placeholder lines={8} />;

  return (
    <div className="narrow">
      <Trail steps={[]} />
      <h1 className="page-title">Departments</h1>
      <p className="standfirst">
        A department groups projects that share ways of working. A project sits in at most one department; a project in
        none reads company memory only. The company’s admins create departments and name their leads; a department lead
        names another lead and moves projects in and out.
      </p>

      {refused && (
        <div style={{ marginTop: 20 }}>
          <Refusal testid="department-refused">{refused}</Refusal>
        </div>
      )}

      {answer.you_may_create && (
        <Adding
          label="New department"
          placeholder="e.g. Payments"
          missing="Enter the department’s name."
          action="Create department"
          testid="department"
          onAdd={(name) => attempt(() => createDepartment(name))}
        />
      )}

      {answer.departments.length === 0 && (
        <p className="empty" data-testid="no-departments" style={{ marginTop: 20 }}>
          No departments yet. Every project reads company memory and its own project memory.
        </p>
      )}

      {answer.departments.map((department) => (
        <OneDepartment
          key={department.department_id}
          department={department}
          runsTheCompany={answer.you_may_create}
          members={current}
          inNone={inNone}
          attempt={attempt}
        />
      ))}
    </div>
  );
}

function OneDepartment({
  department,
  runsTheCompany,
  members,
  inNone,
  attempt,
}: {
  department: DepartmentSummary;
  runsTheCompany: boolean;
  members: MemberSummary[];
  inNone: ProjectSummary[];
  attempt: (what: () => Promise<DepartmentList>) => void;
}) {
  const id = department.department_id;
  return (
    <section aria-label={department.name} data-testid="department" style={{ marginTop: 32 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <h2 className="section-heading" data-testid="department-name">
          {department.name}
        </h2>
        {runsTheCompany && (
          <button
            type="button"
            className="quiet-link danger"
            onClick={() => attempt(() => removeDepartment(id))}
            data-testid="remove-department"
          >
            Remove department
          </button>
        )}
      </div>
      {department.you_lead && <p className="section-lede">You lead this department.</p>}
      {runsTheCompany && <Renaming name={department.name} onRenamed={(name) => attempt(() => renameDepartment(id, name))} />}

      <h3 className="sub-heading">Department leads</h3>
      <ul className="entries" data-testid="department-leads">
        {department.leads.length === 0 && (
          <li className="entry" style={{ color: "var(--ink-3)", fontSize: "0.9375rem" }}>
            Nobody leads this department.
          </li>
        )}
        {department.leads.map((lead) => (
          <li className="entry" key={lead.member_id} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <span>{lead.name}</span>
            {runsTheCompany && (
              <button
                type="button"
                className="quiet-link danger"
                onClick={() => attempt(() => removeDepartmentLead(id, lead.member_id))}
                data-testid={`remove-department-lead-${lead.member_id}`}
              >
                Take off
              </button>
            )}
          </li>
        ))}
      </ul>
      {department.you_may_change && (
        <Choosing
          members={members.filter((one) => !department.leads.some((lead) => lead.member_id === one.member_id))}
          missing="Choose who to appoint."
          action="Appoint as department lead"
          testid="department-lead"
          onChosen={(memberId) => attempt(() => appointDepartmentLead(id, memberId))}
        />
      )}

      <h3 className="sub-heading">Projects</h3>
      <ul className="entries" data-testid="department-projects">
        {department.projects.length === 0 && (
          <li className="entry" style={{ color: "var(--ink-3)", fontSize: "0.9375rem" }}>
            No projects in this department yet.
          </li>
        )}
        {department.projects.map((project) => (
          <li className="entry" key={project.project_id} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <Link to={folderUrl(`projects/${project.project_id}`)}>{project.name}</Link>
            {department.you_may_change && (
              <button
                type="button"
                className="quiet-link danger"
                onClick={() => attempt(() => moveProjectOut(id, project.project_id))}
                data-testid={`move-out-${project.project_id}`}
              >
                Move out
              </button>
            )}
          </li>
        ))}
      </ul>
      {department.you_may_change && (
        <MovingIn projects={inNone} onChosen={(projectId) => attempt(() => moveProjectIn(id, projectId))} />
      )}
    </section>
  );
}

/** Choose a project in no department and move it into this one. */
function MovingIn({ projects, onChosen }: { projects: ProjectSummary[]; onChosen: (projectId: string) => void }) {
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
      <Select
        label="Project in no department"
        placeholder={projects.length === 0 ? "Every project is in a department" : "Choose a project"}
        data={projects.map((one) => ({ value: one.project_id, label: one.name }))}
        value={chosen}
        searchable
        error={tried && !chosen ? "Choose a project to move in." : undefined}
        data-testid="new-department-project"
        onChange={(projectId) => {
          setChosen(projectId);
          setTried(false);
        }}
        style={{ flex: "1 1 260px", maxWidth: 380 }}
      />
      <Button type="submit" variant="default" data-testid="add-department-project">
        Move in
      </Button>
    </form>
  );
}

function Renaming({ name, onRenamed }: { name: string; onRenamed: (name: string) => void }) {
  const [asked, setAsked] = useState(name);
  const missing = !asked.trim() ? "Enter the new name." : asked.trim() === name ? "That is already its name." : null;
  const [tried, setTried] = useState(false);
  return (
    <form
      className="form-line"
      style={{ marginTop: 10, borderTop: 0 }}
      onSubmit={(event) => {
        event.preventDefault();
        if (missing) setTried(true);
        else onRenamed(asked.trim());
      }}
    >
      <TextInput
        label="Name"
        value={asked}
        error={tried ? missing : undefined}
        data-testid="department-new-name"
        onChange={(event) => {
          setAsked(event.currentTarget.value);
          setTried(false);
        }}
        style={{ flex: "1 1 220px", maxWidth: 320 }}
      />
      <Button type="submit" variant="default" data-testid="rename-department">
        Rename
      </Button>
    </form>
  );
}
