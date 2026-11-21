import type { Folder, ProjectSummary } from "../api/client";

export type TopFolder = Folder["folders"][number];

/**
 * The top of the contents in its groups: company memory, then each department by name with its department memory and
 * then its projects, then the projects in no department, headed as such only when there are departments at all
 * (ADR-0032). Under its department's name, a department's memory folder reads as "Department memory".
 */
export function grouped(
  folders: TopFolder[],
  projects: Map<string, ProjectSummary>,
): { heading: string | null; folders: TopFolder[] }[] {
  const departmentOf = (folder: TopFolder) =>
    folder.path.startsWith("projects/") ? (projects.get(folder.path.split("/")[1]!)?.department ?? null) : null;
  const company = folders.filter((folder) => !folder.path.startsWith("projects/") && !folder.path.startsWith("departments/"));
  const inProjects = folders.filter((folder) => folder.path.startsWith("projects/"));
  const departments = new Map<string, { name: string; folders: TopFolder[] }>();
  for (const folder of folders.filter((one) => one.path.startsWith("departments/"))) {
    departments.set(folder.path.split("/")[1]!, { name: folder.name, folders: [{ ...folder, name: "Department memory" }] });
  }
  for (const folder of inProjects) {
    const department = departmentOf(folder);
    if (!department) continue;
    const group = departments.get(department.department_id) ?? { name: department.name, folders: [] };
    group.folders.push(folder);
    departments.set(department.department_id, group);
  }
  const inNone = inProjects.filter((folder) => departmentOf(folder) === null);
  const byName = [...departments.values()].sort((one, other) => one.name.localeCompare(other.name));
  return [
    { heading: null, folders: company },
    ...byName.map((group) => ({ heading: group.name, folders: group.folders })),
    ...(inNone.length > 0 ? [{ heading: byName.length > 0 ? "No department" : null, folders: inNone }] : []),
  ];
}
