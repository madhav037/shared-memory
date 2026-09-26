import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("a member pins a whole topic into every briefing, and unpins it", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "invoicing");
  await expect(page.getByTestId("folder-name")).toHaveText("invoicing");

  await page.getByTestId("pin-topic").click();

  // A pinned topic belongs in the project's briefing, marked as a topic rather than one memory.
  await page.getByRole("navigation", { name: "Where this is" }).getByRole("link", { name: "Billing" }).click();
  const pins = page.getByTestId("pins");
  await expect(pins).toContainText("invoicing");
  await expect(pins).toContainText("(topic)");

  await pins.getByRole("link", { name: /invoicing/ }).click();
  await page.getByTestId("unpin-topic").click();

  await expect(page.getByTestId("pin-topic")).toBeVisible();
  await page.getByRole("navigation", { name: "Where this is" }).getByRole("link", { name: "Billing" }).click();
  await expect(page.getByTestId("pins")).toContainText("Nothing is pinned");
});
