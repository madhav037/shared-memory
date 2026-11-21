import { Link, useParams } from "react-router";

import { fetchDepartment, type MemoryCounts } from "../api/client";
import { Placeholder, Refusal, RestrictedMark, Trail } from "../components/Bits";
import { folderUrl, memoryUrl, plural, typeName } from "../lib/format";
import { useAsked } from "../lib/useAsked";

/** The counts of the roll-up, in the order its columns read. */
const COLUMNS: { key: keyof MemoryCounts; label: string }[] = [
  { key: "memories", label: "Memories" },
  { key: "possibly_outdated", label: "Possibly outdated" },
  { key: "used", label: "Used lately" },
  { key: "level_contradictions", label: "Level contradictions waiting" },
  { key: "challenges", label: "Challenges waiting" },
];

/**
 * One department's page (#636): the projects in it, the department memory they share and, for its department leads and
 * the company's admins, how memory is doing in each project and in department memory. Counts only, never per member
 * (spec #624). It only reads: leads, projects and access are changed on the Departments page, and memory from a
 * session or its own page (ADR-0009).
 */
export function DepartmentPage() {
  const { departmentId = "" } = useParams();
  const { answer: department, refused } = useAsked((signal) => fetchDepartment(departmentId, signal), [departmentId]);

  if (refused)
    return (
      <div className="narrow">
        <Trail steps={[]} />
        <Refusal testid="department-page-refused">{refused}</Refusal>
      </div>
    );
  if (!department) return <Placeholder lines={10} />;

  return (
    <div className="narrow">
      <Trail steps={[]} />
      <h1 className="page-title" data-testid="department-page-name">
        {department.name}
      </h1>
      {department.restricted && <RestrictedMark />}
      <p className="standfirst">
        The projects in this department and the department memory every one of them reads.{" "}
        {department.you_lead ? "You lead this department. " : ""}Nothing here changes memory; leads, projects and
        access are changed on the <Link to="/departments">Departments</Link> page.
      </p>

      <section aria-labelledby="projects-heading">
        <h2 className="section-heading" id="projects-heading">
          Projects
        </h2>
        <ul className="entries" data-testid="department-page-projects">
          {department.projects.length === 0 && <Nothing>No project you can reach is in this department.</Nothing>}
          {department.projects.map((project) => (
            <li className="entry" key={project.project_id}>
              <Link className="entry-title" to={folderUrl(`projects/${project.project_id}`)}>
                {project.name}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="department-memory-heading">
        <h2 className="section-heading" id="department-memory-heading">
          Department memory
        </h2>
        <p className="section-lede">Holds for every project in this department.</p>
        <ul className="entries" data-testid="department-page-memory">
          {department.memory.length === 0 && <Nothing>This department has no department memory yet.</Nothing>}
          {department.memory.map((memory) => (
            <li className="entry" key={memory.path} data-testid="department-memory-entry">
              <Link className="entry-title" to={memoryUrl(memory.path)}>
                {memory.title}
              </Link>
              <p className="entry-summary">{memory.summary}</p>
              <div className="entry-meta">
                <span>{typeName(memory.type)}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {department.roll_up && (
        <section aria-labelledby="roll-up-heading" data-testid="roll-up">
          <h2 className="section-heading" id="roll-up-heading">
            How memory is doing
          </h2>
          <p className="section-lede">
            Counts only, never per member. Possibly outdated means no coding agent has recalled or read it for{" "}
            {plural(department.roll_up.outdated_after_days, "day")}; used lately means recalled, read or saved in the
            last {plural(department.roll_up.window_days, "day")}.
          </p>
          <div className="scroll-x">
            <table className="register">
              <thead>
                <tr>
                  <th scope="col">Where</th>
                  {COLUMNS.map((column) => (
                    <th scope="col" key={column.key}>
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {department.roll_up.projects.map((project) => (
                  <Row key={project.project_id} name={project.name} counts={project.counts} testid="roll-up-project" />
                ))}
                <Row
                  name="Department memory"
                  counts={department.roll_up.department_memory}
                  testid="roll-up-department-memory"
                />
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function Row({ name, counts, testid }: { name: string; counts: MemoryCounts; testid: string }) {
  return (
    <tr data-testid={testid}>
      <th scope="row">{name}</th>
      {COLUMNS.map((column) => (
        <td key={column.key} data-testid={`count-${column.key}`}>
          {counts[column.key]}
        </td>
      ))}
    </tr>
  );
}

function Nothing({ children }: { children: React.ReactNode }) {
  return (
    <li className="entry" style={{ color: "var(--ink-3)", fontSize: "0.9375rem" }} data-testid="nothing">
      {children}
    </li>
  );
}
