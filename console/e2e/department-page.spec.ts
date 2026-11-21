import { expect, test } from "@playwright/test";

import { signInAs, signOut, teammates } from "./helpers";

test("a department lead opens the department page and sees each project's counts and department memory's use, never a member's name; a member who leads nothing sees its projects and memory but no roll-up", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");

  // A project of this journey's own, named to sort after Billing so the other journeys' contents keep their order.
  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Spinney");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveText("Spinney");
  const projectId = decodeURIComponent(new URL(page.url()).pathname.split("/")[2]!);

  // Olive makes a department, leads it herself and moves Spinney into it.
  await page.goto("/departments");
  await page.getByTestId("new-department").fill("Hedgerow");
  await page.getByTestId("add-department").click();
  const hedgerow = page.getByTestId("department").filter({ hasText: "Hedgerow" });
  await hedgerow.getByTestId("new-department-lead").fill("Olive");
  await page.getByRole("option", { name: /Olive Owner/ }).click();
  await hedgerow.getByTestId("add-department-lead").click();
  await expect(hedgerow.getByTestId("department-leads")).toContainText("Olive Owner");
  await hedgerow.getByTestId("new-department-project").click();
  await page.getByRole("option", { name: "Spinney", exact: true }).click();
  await hedgerow.getByTestId("add-department-project").click();
  await expect(hedgerow.getByTestId("department-projects")).toContainText("Spinney");

  // Her coding agent, in Spinney, promotes a way of working into Hedgerow's department memory.
  const promoted = await page.request.post(`${teammates}/department-memory?project_id=${encodeURIComponent(projectId)}`);
  expect(promoted.ok()).toBe(true);

  // The department page: its projects, its department memory, and the roll-up, counts only.
  await hedgerow.getByTestId("to-department-page").click();
  await expect(page.getByTestId("department-page-name")).toHaveText("Hedgerow");
  const departmentUrl = page.url();
  await expect(page.getByTestId("department-page-projects")).toContainText("Spinney");
  await expect(page.getByTestId("department-page-memory")).toContainText("Every change ships behind a flag");
  const spinney = page.getByTestId("roll-up-project").filter({ hasText: "Spinney" });
  await expect(spinney.getByTestId("count-memories")).toHaveText("0");
  await expect(spinney.getByTestId("count-possibly_outdated")).toHaveText("0");
  await expect(spinney.getByTestId("count-level_contradictions")).toHaveText("0");
  await expect(spinney.getByTestId("count-challenges")).toHaveText("0");
  const departmentMemory = page.getByTestId("roll-up-department-memory");
  await expect(departmentMemory.getByTestId("count-memories")).toHaveText("1");
  await expect(departmentMemory.getByTestId("count-used")).toHaveText("1");
  await expect(page.locator("main")).not.toContainText("Olive");
  // Read-only: nothing on the page saves, pins, retires or decides.
  await expect(page.locator("main button")).toHaveCount(0);

  // Dana leads nothing: she sees the department's projects and memory, but no roll-up.
  await signOut(page);
  await signInAs(page, 2, "dana");
  await page.goto(departmentUrl);
  await expect(page.getByTestId("department-page-name")).toHaveText("Hedgerow");
  await expect(page.getByTestId("department-page-projects")).toContainText("Spinney");
  await expect(page.getByTestId("department-page-memory")).toContainText("Every change ships behind a flag");
  await expect(page.getByTestId("roll-up")).toHaveCount(0);

  // Removing Hedgerow retires its memory and leaves the contents as every other journey expects them.
  await signOut(page);
  await signInAs(page, 1, "olive");
  await page.goto("/departments");
  await page.getByTestId("department").filter({ hasText: "Hedgerow" }).getByTestId("remove-department").click();
  await expect(page.getByTestId("department").filter({ hasText: "Hedgerow" })).toHaveCount(0);
  await expect(page.getByRole("tree", { name: "Contents" }).getByTestId("tree-department")).toHaveCount(0);
});
