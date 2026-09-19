import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("a member moves through a memory's history, back past its promotion", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  const versions = page.getByTestId("versions").locator("li");
  await expect(versions.first()).toContainText("Promoted by Olive Owner");
  await expect(versions.last()).toContainText("First written by Olive Owner");

  await page.getByTestId("version-row").last().click();

  await expect(page.getByTestId("history-stamp")).toContainText("As it stood: version 1");
  await expect(page.getByTestId("history-stamp")).toContainText("First written by Olive Owner");
  await expect(page.getByTestId("version-text")).toContainText("second lockfile");
  await expect(page.getByTestId("memory-body")).toHaveCount(0);

  await page.getByTestId("back-to-now").click();

  await expect(page.getByTestId("memory-body")).toContainText("second lockfile");
  await expect(page.getByTestId("version-text")).toHaveCount(0);
});
