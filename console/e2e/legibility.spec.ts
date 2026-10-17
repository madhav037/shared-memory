import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("the contents names every folder and memory on the panel, and cuts a long name with an ellipsis", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Gotchas");

  // A name sits on the panel itself: no fill behind it, whatever another page calls a label.
  const folder = page.locator(".contents-column .tree-row", { hasText: "Billing" }).first().locator(".label");
  await expect(folder).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");

  // A name too long for the column ends in an ellipsis rather than mid-letter, and says itself in full on hover.
  const leaf = page.locator(".contents-column .tree-row", { hasText: "The API rate limit" }).first();
  const name = leaf.locator(".label-text");
  await expect(name).toHaveCSS("text-overflow", "ellipsis");
  await expect(name).toHaveCSS("white-space", "nowrap");
  await expect(leaf).toHaveAttribute("title", /^The API rate limit is 100 a minute\n/);
});

test("a memory's history slider says what it moves through to a screen reader", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  await expect(page.getByRole("slider", { name: "Read it as it stood at" })).toBeVisible();
});

test("a repository file wider than the page can be scrolled from the keyboard", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByRole("link", { name: "Settings" }).first().click();

  const file = page.locator("pre.settings-block").first();
  await expect(file).toHaveAttribute("tabindex", "0");
  await expect(file).toHaveAttribute("role", "region");
  await expect(file).toHaveAttribute("aria-label", /.+/);
});
