import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("the audit log narrows to one member", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-audit").click();

  // Found by member ID; the option names who that is.
  await page.getByTestId("filter-member").fill("emp-dana");
  await page.getByRole("option", { name: /Raj Raiser/ }).click();

  // Only the Who column: a row of Raj's can still name Olive in its details, as a challenge he raised does.
  const who = page.getByTestId("audit-table").locator("tbody tr .who-cell");
  await expect(who.first()).toHaveText("Raj Raiser");
  await expect(who.filter({ hasNotText: "Raj Raiser" })).toHaveCount(0);
});

test("the audit log narrows to one project", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-audit").click();

  await page.getByTestId("filter-project").click();
  await page.getByRole("option", { name: "Billing" }).click();

  const where = page.getByTestId("audit-table").locator("tbody tr .where-cell");
  await expect(where.first()).toContainText("Billing");
  await expect(where.filter({ hasNotText: "Billing" })).toHaveCount(0);
  // A memory is named by its title first, and its path follows, quieter.
  await expect(where.locator(".audit-memory").first()).toBeVisible();
  await expect(where.locator(".where-path").first()).toContainText(/\.md$/);
});

test("the audit log narrows to a day, and says so when nothing happened on it", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-audit").click();
  await expect(page.getByTestId("audit-table")).toBeVisible();

  // The journeys run on a clock that does not move, so every change in the register is stamped the same day.
  await page.getByTestId("filter-since").fill("2026-09-02");
  await expect(page.getByTestId("audit-empty")).toBeVisible();

  await page.getByTestId("filter-since").fill("");
  await page.getByTestId("filter-until").fill("2026-08-31");
  await expect(page.getByTestId("audit-empty")).toBeVisible();

  await page.getByTestId("filter-until").fill("2026-09-01");
  await expect(page.getByTestId("audit-table")).toBeVisible();
});
