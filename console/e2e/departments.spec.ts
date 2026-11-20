import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("an admin creates a department, names a lead and moves a project in, and the contents group it", async ({ page }) => {
  await signInAs(page, 1, "olive");

  // A project of this journey's own, named to sort after Billing so the other journeys' contents keep their order.
  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Quarry");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveText("Quarry");
  await expect(page.getByTestId("project-department")).toContainText("In no department");

  await page.getByTestId("to-company").click();
  await page.getByTestId("to-departments").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Departments");
  await page.getByTestId("new-department").fill("Platform");
  await page.getByTestId("add-department").click();

  const platform = page.getByTestId("department").filter({ hasText: "Platform" });
  await expect(platform.getByTestId("department-leads")).toContainText("Nobody leads this department");
  await platform.getByTestId("new-department-lead").fill("Raj");
  await page.getByRole("option", { name: /Raj Raiser/ }).click();
  await platform.getByTestId("add-department-lead").click();
  await expect(platform.getByTestId("department-leads")).toContainText("Raj Raiser");

  await platform.getByTestId("new-department-project").click();
  await page.getByRole("option", { name: "Quarry", exact: true }).click();
  await platform.getByTestId("add-department-project").click();
  await expect(platform.getByTestId("department-projects")).toContainText("Quarry");

  const contents = page.getByRole("tree", { name: "Contents" });
  await expect(contents.getByTestId("tree-department").first()).toHaveText("Platform");
  await expect(contents.getByTestId("tree-department").last()).toHaveText("No department");
  await expect(contents.getByRole("treeitem", { name: /^Quarry/ })).toBeVisible();

  await platform.getByRole("link", { name: "Quarry" }).click();
  await page.getByRole("navigation", { name: "This project’s pages" }).getByTestId("to-settings").click();
  await expect(page.getByTestId("project-department")).toContainText("In the department Platform");

  // Removing it leaves Quarry in no department, and the contents as every other journey expects them.
  await page.goto("/departments");
  await page.getByTestId("department").filter({ hasText: "Platform" }).getByTestId("remove-department").click();
  await expect(page.getByTestId("no-departments")).toBeVisible();
  await expect(contents.getByTestId("tree-department")).toHaveCount(0);
});
