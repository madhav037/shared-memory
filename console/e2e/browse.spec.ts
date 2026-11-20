import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a member opens a project, reads a memory, and finds it by searching", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await page.getByTestId("projects").getByRole("link", { name: /Billing/ }).first().click();
  await page.getByTestId("subfolder").filter({ hasText: "Project memory" }).click();
  await page.getByTestId("subfolder").filter({ hasText: "Conventions" }).click();
  await page.getByRole("link", { name: "Use pnpm, not npm" }).first().click();

  await expect(page.getByTestId("memory-title")).toHaveText("Use pnpm, not npm");
  await expect(page.getByTestId("memory-body")).toContainText("second lockfile");

  await page.getByTestId("masthead-search").fill("which package manager do we use");
  await page.getByTestId("masthead-search").press("Enter");

  await expect(page.getByTestId("results")).toContainText("Use pnpm, not npm");
  await expect(page.getByTestId("results")).toContainText("Project memory");
});

test("the contents open with company memory, which holds for every project in the company", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await expect(page.getByTestId("project-card").first()).toContainText("Company memory");
  await expect(page.getByTestId("company-note")).toContainText("Holds for every project in the company.");
  await expect(page.getByTestId("project-card").first()).not.toContainText("Team memory");
});
