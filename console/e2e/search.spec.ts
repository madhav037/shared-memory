import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a member searches from the search page and finds what they meant, not what they typed", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-search").click();

  await page.getByTestId("search").fill("which package manager do we use");
  await page.getByTestId("search-go").click();

  // The memory says pnpm and npm, and never "package manager".
  await expect(page.getByTestId("results")).toContainText("Use pnpm, not npm");
  await expect(page.getByTestId("results")).toContainText("Billing");
});

test("a search narrowed to a type nothing here was written as says so", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-search").click();
  await page.getByTestId("search").fill("which package manager do we use");
  await page.getByTestId("search-go").click();
  await expect(page.getByTestId("results")).toContainText("Use pnpm, not npm");

  await page.getByTestId("type").getByRole("button", { name: "Architecture" }).click();

  await expect(page.getByTestId("nothing-found")).toContainText("Nothing matches");
  await expect(page.getByTestId("nothing-found")).toContainText("with those filters");
  await expect(page.getByTestId("results")).toHaveCount(0);
});

test("results with the words searched for come first, and the ones only close in meaning are set apart", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-search").click();
  await page.getByTestId("search").fill("lockfile");
  await page.getByTestId("search-go").click();

  // Only one memory says "lockfile". Everything else found is near it in meaning, and weaker for it.
  await expect(page.getByTestId("results-count")).toContainText("One memory has the words you searched for");
  await expect(page.getByTestId("worded").locator(".entry")).toHaveCount(1);
  await expect(page.getByTestId("worded")).toContainText("Use pnpm, not npm");
  await expect(page.getByRole("heading", { name: "Weaker matches" })).toBeVisible();
  await expect(page.getByTestId("close")).not.toContainText("Use pnpm, not npm");
});
