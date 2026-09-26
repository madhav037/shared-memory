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
