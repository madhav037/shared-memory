import { expect, test } from "@playwright/test";

import { signInAs, teammates } from "./helpers";

test("department memory a lead's session promotes shows under its department in the contents, with its level, and the level filter finds it; a non-lead's promotion is a challenge its lead accepts on the challenges screen", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");

  // A project of this journey's own, named to sort after the other journeys' projects so their contents keep their order.
  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Rookery");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveText("Rookery");
  const projectId = decodeURIComponent(new URL(page.url()).pathname.split("/")[2]!);

  // Olive makes a department, leads it herself and moves Rookery into it.
  await page.goto("/departments");
  await page.getByTestId("new-department").fill("Guild");
  await page.getByTestId("add-department").click();
  const guild = page.getByTestId("department").filter({ hasText: "Guild" });
  await guild.getByTestId("new-department-lead").fill("Olive");
  await page.getByRole("option", { name: /Olive Owner/ }).click();
  await guild.getByTestId("add-department-lead").click();
  await expect(guild.getByTestId("department-leads")).toContainText("Olive Owner");
  await guild.getByTestId("new-department-project").click();
  await page.getByRole("option", { name: "Rookery", exact: true }).click();
  await guild.getByTestId("add-department-project").click();
  await expect(guild.getByTestId("department-projects")).toContainText("Rookery");

  // Her coding agent, in Rookery, promotes a way of working into Guild's department memory.
  const promoted = await page.request.post(`${teammates}/department-memory?project_id=${encodeURIComponent(projectId)}`);
  expect(promoted.ok()).toBe(true);
  const { path } = (await promoted.json()) as { path: string };
  expect(path).toMatch(/^departments\//);

  // The contents head Guild's department memory with the department's name, before its projects.
  await page.reload();
  const contents = page.getByRole("tree", { name: "Contents" });
  await expect(contents.getByTestId("tree-department").first()).toHaveText("Guild");
  const departmentMemory = contents.getByRole("treeitem", { name: /^Department memory, 1 memory/ });
  await expect(departmentMemory).toBeVisible();
  await departmentMemory.locator(".tree-row").first().click();
  const conventions = departmentMemory.getByRole("treeitem", { name: /^Conventions/ });
  await conventions.locator(".tree-row").first().click();
  await conventions.getByRole("treeitem", { name: /^Every change ships behind a flag/ }).click();
  await expect(page.getByTestId("memory-title")).toContainText("Every change ships behind a flag");
  await expect(page.locator(".rank").first()).toHaveText("Department memory");
  await expect(page.getByTestId("in-force")).toContainText("every project in its department");

  // Search narrowed to department memory finds it, and narrowed to company memory doesn't.
  await page.getByTestId("to-search").click();
  await page.getByTestId("search").fill("feature flag");
  await page.getByTestId("search-go").click();
  await page.getByTestId("level").getByRole("button", { name: "Department" }).click();
  await expect(page.getByTestId("results")).toContainText("Every change ships behind a flag");
  await expect(page.getByTestId("results")).toContainText("Department memory");
  await page.getByTestId("level").getByRole("button", { name: "Company" }).click();
  await expect(page.getByTestId("results").getByText("Every change ships behind a flag")).toHaveCount(0);

  // Mira, who doesn't lead Guild, asks to promote a memory of hers into it: a challenge Olive decides as its lead.
  const asked = await page.request.post(`${teammates}/department-challenge?project_id=${encodeURIComponent(projectId)}`);
  expect(asked.ok()).toBe(true);
  expect(((await asked.json()) as { status: string }).status).toBe("challenge_raised");
  await page.getByTestId("to-challenges").click();
  await expect(page.getByRole("heading", { name: "Department challenges" })).toBeVisible();
  const asking = page.getByTestId("department-challenges");
  await expect(asking.getByTestId("department-mark")).toHaveText("Guild department");
  await expect(asking).toContainText("Releases go out on Tuesdays");
  await expect(asking).toContainText("Mira Maker wants to promote it into department memory");
  await expect(asking).toContainText("yours to decide as a department lead");
  await expect(asking.getByTestId("reasoning-text")).toHaveText(
    "Every team here releases on Tuesdays already; writing it down saves each new member asking.",
  );
  await asking.getByRole("button", { name: "Accept: promote it into department memory" }).click();
  const slip = page.getByTestId("decided");
  await expect(slip).toContainText("You accepted it. ‘Releases go out on Tuesdays’ is now Guild department memory.");
  await expect(page.getByTestId("department-challenges")).toHaveCount(0);
  await slip.getByRole("link", { name: "Read it" }).click();
  await expect(page.getByTestId("memory-title")).toContainText("Releases go out on Tuesdays");
  await expect(page.locator(".rank").first()).toHaveText("Department memory");

  // Removing Guild retires its memory and leaves the contents as every other journey expects them.
  await page.goto("/departments");
  await page.getByTestId("department").filter({ hasText: "Guild" }).getByTestId("remove-department").click();
  await expect(page.getByTestId("department").filter({ hasText: "Guild" })).toHaveCount(0);
  await expect(contents.getByTestId("tree-department")).toHaveCount(0);
  await page.goto(`/memory?path=${encodeURIComponent(path)}`);
  await expect(page.getByTestId("memory-title")).toContainText("Every change ships behind a flag");
  await expect(page.getByTestId("retired-banner")).toBeVisible();
});
