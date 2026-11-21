import { describe, expect, it } from "vitest";

import type { ProjectSummary } from "../api/client";
import { grouped } from "./departments";

const folder = (path: string, name: string) => ({ path, name, kind: "project", memories: 0, changed: null });

const project = (projectId: string, department: ProjectSummary["department"]): ProjectSummary => ({
  project_id: projectId,
  name: projectId,
  restricted: false,
  leads: [],
  you_lead: false,
  department,
});

describe("the top of the contents, grouped by department", () => {
  it("puts company memory first, then each department by name with its projects, then the projects in none", () => {
    const folders = [
      folder("company", "Company memory"),
      folder("projects/billing", "Billing"),
      folder("projects/ledger", "Ledger"),
      folder("projects/site", "Site"),
    ];
    const projects = new Map([
      ["billing", project("billing", { department_id: "payments-1", name: "Payments" })],
      ["ledger", project("ledger", { department_id: "accounts-1", name: "Accounts" })],
      ["site", project("site", null)],
    ]);

    const groups = grouped(folders, projects).map((group) => [group.heading, group.folders.map((one) => one.name)]);

    expect(groups).toEqual([
      [null, ["Company memory"]],
      ["Accounts", ["Ledger"]],
      ["Payments", ["Billing"]],
      ["No department", ["Site"]],
    ]);
  });

  it("puts a department's memory first under its name, as department memory, then its projects", () => {
    const folders = [
      folder("company", "Company memory"),
      folder("departments/payments-1", "Payments"),
      folder("departments/research-1", "Research"),
      folder("projects/billing", "Billing"),
      folder("projects/site", "Site"),
    ];
    const projects = new Map([
      ["billing", project("billing", { department_id: "payments-1", name: "Payments" })],
      ["site", project("site", null)],
    ]);

    const groups = grouped(folders, projects).map((group) => [group.heading, group.folders.map((one) => one.name)]);

    expect(groups).toEqual([
      [null, ["Company memory"]],
      ["Payments", ["Department memory", "Billing"]],
      ["Research", ["Department memory"]],
      ["No department", ["Site"]],
    ]);
  });

  it("heads nothing when the company has no departments, so the contents read as before", () => {
    const folders = [folder("company", "Company memory"), folder("projects/site", "Site")];

    const groups = grouped(folders, new Map([["site", project("site", null)]]));

    expect(groups.map((group) => group.heading)).toEqual([null, null]);
  });
});
