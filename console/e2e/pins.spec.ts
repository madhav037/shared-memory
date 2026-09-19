import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("a member pins a memory, sees it in the project's briefing, and unpins it", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  await page.getByTestId("pin").click();
  await expect(page.getByTestId("memory-details")).toContainText("Pinned");

  await page.getByRole("navigation", { name: "Where this is" }).getByRole("link", { name: "Billing" }).click();
  const pins = page.getByTestId("pins");
  await expect(pins).toContainText("Use pnpm, not npm");
  await expect(pins).toContainText("tokens");

  await pins.getByTestId("unpin-memory").click();
  await expect(page.getByTestId("pins")).toContainText("Nothing is pinned");
});
