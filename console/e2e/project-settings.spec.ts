import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a lead renames their project, and the contents follow the new name", async ({ page }) => {
  await signInAs(page, 1, "olive");

  // A project of this journey's own: renaming Billing would move the ground under every other journey.
  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Ledger");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveText("Ledger");
  await expect(page.getByTestId("you-lead")).toContainText("You lead this project");

  await page.getByTestId("project-new-name").fill("Ledger Core");
  await page.getByTestId("rename-project").click();

  await expect(page.getByTestId("project-name")).toHaveText("Ledger Core");
  await page.getByTestId("to-contents").click();
  await expect(page.getByRole("tree", { name: "Contents" })).toContainText("Ledger Core");
});

test("a member who leads nothing reads a project's settings and can change none of it", async ({ page }) => {
  await signInAs(page, 2, "dana");
  await page.getByTestId("project-card").filter({ hasText: "Billing" }).getByRole("link", { name: "Settings" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings");
  await expect(page.getByTestId("project-name")).toHaveText("Billing");
  await expect(page.getByTestId("read-only")).toContainText("You can read everything here");
  await expect(page.getByTestId("you-lead")).toHaveCount(0);
  await expect(page.getByTestId("project-new-name")).toHaveCount(0);
  await expect(page.getByTestId("rename-project")).toHaveCount(0);
});
