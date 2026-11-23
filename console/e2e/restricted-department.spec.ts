import { expect, test } from "@playwright/test";

import { signInAs, signOut } from "./helpers";

test("a department lead restricts their department and keeps its access list, and an outsider can't see it", async ({ page }) => {
  await signInAs(page, 1, "olive");

  // Lena leads the department; Mira stays outside it. No member is added: the company is at its member cap.
  // A project of this journey's own, named to sort after the others, in a department Lena leads.
  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Vellum");
  await page.getByTestId("create-project").click();
  const projectId = ((await page.getByTestId("project-id").textContent()) ?? "").trim();

  await page.goto("/departments");
  await page.getByTestId("new-department").fill("Strongroom");
  await page.getByTestId("add-department").click();
  const strongroom = page.getByTestId("department").filter({ hasText: "Strongroom" });
  await strongroom.getByTestId("new-department-lead").fill("Lena");
  await page.getByRole("option", { name: /Lena Lead/ }).click();
  await strongroom.getByTestId("add-department-lead").click();
  await expect(strongroom.getByTestId("department-leads")).toContainText("Lena Lead");
  await strongroom.getByTestId("new-department-project").click();
  await page.getByRole("option", { name: "Vellum", exact: true }).click();
  await strongroom.getByTestId("add-department-project").click();
  await expect(strongroom.getByTestId("department-projects")).toContainText("Vellum");

  // Lena, its lead, restricts it and keeps its access list.
  await signOut(page);
  await signInAs(page, 79, "lena");
  await page.goto("/departments");
  const hers = page.getByTestId("department").filter({ hasText: "Strongroom" });
  await expect(hers.getByTestId("department-reach")).toContainText("Every member of the company");
  await hers.getByTestId("restrict-department").click();
  await expect(hers.getByTestId("department-restricted")).toBeVisible();
  await expect(hers.getByTestId("department-access")).toContainText("Nobody has been let in yet");
  await hers.getByTestId("new-department-access").fill("mira");
  await page.getByRole("option", { name: /Mira Maker/ }).click();
  await hers.getByTestId("add-department-access").click();
  await expect(hers.getByTestId("department-access")).toContainText("Mira Maker");
  await hers.getByTestId("revoke-department-emp-mira").click();
  await expect(hers.getByTestId("department-access")).toContainText("Nobody has been let in yet");

  // Mira, outside it, sees neither the department nor its project, and opening it is refused.
  await signOut(page);
  await signInAs(page, 3, "mira");
  await page.goto("/departments");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Departments");
  await expect(page.getByTestId("department").filter({ hasText: "Strongroom" })).toHaveCount(0);
  await expect(page.getByRole("tree", { name: "Contents" }).getByRole("treeitem", { name: /^Vellum/ })).toHaveCount(0);
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("folder-refused")).toContainText("is restricted");

  // A restricted department still holding a project can't be removed: its project is moved out first. Removing it then
  // leaves the contents as every other journey expects them.
  await signOut(page);
  await signInAs(page, 1, "olive");
  await page.goto("/departments");
  const olives = page.getByTestId("department").filter({ hasText: "Strongroom" });
  await olives.getByTestId("remove-department").click();
  await expect(page.getByTestId("department-refused")).toContainText("Move its projects out first");
  await expect(olives).toHaveCount(1);
  await olives.getByTestId(`move-out-${projectId}`).click();
  await expect(olives.getByTestId("department-projects")).toContainText("No projects in this department yet");
  await olives.getByTestId("remove-department").click();
  await expect(page.getByTestId("department").filter({ hasText: "Strongroom" })).toHaveCount(0);
});
