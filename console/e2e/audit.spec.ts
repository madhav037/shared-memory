import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("the owner signs in and finds that sign-in in the audit log", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-audit").click();

  const rows = page.getByTestId("audit-table").locator("tbody tr");
  await expect(rows.first()).toContainText("Olive Owner");
  await expect(rows.first()).toContainText("Signed in");
  await expect(page.getByTestId("audit-showing")).toHaveText(/^Showing (the latest|all) \d+ changes\.$/);

  await page.getByTestId("filter-kind").click();
  await page.getByRole("option", { name: "Sign-in refused" }).click();

  await expect(page.getByTestId("audit-empty")).toBeVisible();
});
