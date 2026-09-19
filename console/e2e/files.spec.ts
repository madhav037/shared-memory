import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("a member finds memory in the folder structure and reads the file exactly as Claude reads it", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  await expect(page.getByTestId("memory-title")).toHaveText("Use pnpm, not npm");
  await expect(page.getByRole("navigation", { name: "Where this is" })).toContainText("Billing");
  await expect(page.getByRole("navigation", { name: "Where this is" })).toContainText("Conventions");

  await page.getByTestId("view-source").click();
  await expect(page.getByTestId("memory-source")).toContainText("title: Use pnpm, not npm");
  await expect(page.getByTestId("memory-source")).toContainText("type: convention");
  await expect(page.getByTestId("memory-source")).toContainText("second lockfile");
});

test("the contents are a tree the keyboard can walk", async ({ page }) => {
  await signInAs(page, 1, "olive");

  const tree = page.getByRole("tree", { name: "Contents" });
  await tree.getByRole("treeitem").first().focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");

  await expect(tree.getByRole("treeitem", { name: /^Billing/ })).toHaveAttribute("aria-expanded", "true");
  await expect(tree.getByRole("treeitem", { name: /^Project memory/ })).toBeVisible();
});
