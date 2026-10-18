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

  // Only one memory says "lockfile". Everything else found is near it in meaning, and weaker for it, so it stays
  // folded away until asked for.
  await expect(page.getByTestId("results-count")).toContainText("One memory has the words you searched for");
  await expect(page.getByTestId("worded").locator(".entry")).toHaveCount(1);
  await expect(page.getByTestId("worded")).toContainText("Use pnpm, not npm");
  const fold = page.getByTestId("weaker-toggle");
  await expect(fold).toHaveText(/^Show \d+ weaker match/);
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("close")).toHaveCount(0);

  await fold.click();
  await expect(fold).toHaveAttribute("aria-expanded", "true");
  await expect(fold).toHaveText(/^Hide the/);
  await expect(page.getByTestId("close")).toBeVisible();
  await expect(page.getByTestId("close")).not.toContainText("Use pnpm, not npm");
});

test("a search no memory has the words of says so first, and keeps what comes close in meaning folded", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-search").click();
  await page.getByTestId("search").fill("zebra quantum lighthouse");
  await page.getByTestId("search-go").click();

  // Meaning always finds something; none of it is what was asked for, and the page says that before anything else.
  await expect(page.getByTestId("results-count")).toHaveText("No memory has the words “zebra quantum lighthouse”.");
  await expect(page.getByTestId("no-words")).toContainText("Check the spelling.");
  await expect(page.getByTestId("no-words")).toContainText("Try fewer words");
  await expect(page.getByTestId("clear-filters")).toHaveCount(0);
  await expect(page.getByTestId("no-words").getByRole("link", { name: "Contents" })).toHaveAttribute("href", "/");
  const fold = page.getByTestId("weaker-toggle");
  await expect(fold).toHaveText(/^Show \d+ that come close in meaning$/);
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("close")).toHaveCount(0);

  await fold.click();
  await expect(fold).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("close").locator(".entry").first()).toBeVisible();
  await expect(page.getByTestId("weaker")).toContainText("None of these has the words you searched for.");

  // With a filter on, clearing it is one of the ways out.
  await page.getByTestId("level").getByRole("button", { name: "Project" }).click();
  await expect(page.getByTestId("results-count")).toContainText("with those filters");
  await page.getByTestId("clear-filters").click();
  await expect(page.getByTestId("level").getByRole("button", { name: "Every level" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByTestId("clear-filters")).toHaveCount(0);
});
