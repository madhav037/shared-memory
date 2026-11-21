import { expect, test } from "@playwright/test";

import { signInAs, signOut } from "./helpers";

test("a department lead restricts their department and keeps its access list, and an outsider can't see it", async ({ page }) => {
  await signInAs(page, 1, "olive");

  // A lead for the department, and a member who stays outside it.
  await page.getByTestId("to-company").click();
  for (const [memberId, name, github] of [
    ["emp-ida", "Ida Inside", "ida-inside"],
    ["emp-otto", "Otto Outside", "otto-outside"],
  ]) {
    await page.getByTestId("new-member-id").fill(memberId!);
    await page.getByTestId("new-name").fill(name!);
    await page.getByTestId("new-github").fill(github!);
    await page.getByTestId("add-member").click();
    await expect(page.getByTestId("members")).toContainText(name!);
  }

  // A project of this journey's own, named to sort after the others, in a department Ida leads.
  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Vellum");
  await page.getByTestId("create-project").click();
  const projectId = ((await page.getByTestId("project-id").textContent()) ?? "").trim();

  await page.goto("/departments");
  await page.getByTestId("new-department").fill("Strongroom");
  await page.getByTestId("add-department").click();
  const strongroom = page.getByTestId("department").filter({ hasText: "Strongroom" });
  await strongroom.getByTestId("new-department-lead").fill("Ida");
  await page.getByRole("option", { name: /Ida Inside/ }).click();
  await strongroom.getByTestId("add-department-lead").click();
  await expect(strongroom.getByTestId("department-leads")).toContainText("Ida Inside");
  await strongroom.getByTestId("new-department-project").click();
  await page.getByRole("option", { name: "Vellum", exact: true }).click();
  await strongroom.getByTestId("add-department-project").click();
  await expect(strongroom.getByTestId("department-projects")).toContainText("Vellum");

  // Ida, its lead, restricts it and keeps its access list.
  await signOut(page);
  await signInAs(page, 91, "ida-inside");
  await page.goto("/departments");
  const hers = page.getByTestId("department").filter({ hasText: "Strongroom" });
  await expect(hers.getByTestId("department-reach")).toContainText("Every member of the company");
  await hers.getByTestId("restrict-department").click();
  await expect(hers.getByTestId("department-restricted")).toBeVisible();
  await expect(hers.getByTestId("department-access")).toContainText("Nobody has been let in yet");
  await hers.getByTestId("new-department-access").fill("otto");
  await page.getByRole("option", { name: /Otto Outside/ }).click();
  await hers.getByTestId("add-department-access").click();
  await expect(hers.getByTestId("department-access")).toContainText("Otto Outside");
  await hers.getByTestId("revoke-department-emp-otto").click();
  await expect(hers.getByTestId("department-access")).toContainText("Nobody has been let in yet");

  // Otto, outside it, sees neither the department nor its project, and opening it is refused.
  await signOut(page);
  await signInAs(page, 92, "otto-outside");
  await page.goto("/departments");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Departments");
  await expect(page.getByTestId("department").filter({ hasText: "Strongroom" })).toHaveCount(0);
  await expect(page.getByRole("tree", { name: "Contents" }).getByRole("treeitem", { name: /^Vellum/ })).toHaveCount(0);
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("folder-refused")).toContainText("is restricted");

  // Removing the department leaves the contents as every other journey expects them.
  await signOut(page);
  await signInAs(page, 1, "olive");
  await page.goto("/departments");
  await page.getByTestId("department").filter({ hasText: "Strongroom" }).getByTestId("remove-department").click();
  await expect(page.getByTestId("department").filter({ hasText: "Strongroom" })).toHaveCount(0);
});
