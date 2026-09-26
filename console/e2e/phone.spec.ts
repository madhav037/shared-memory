import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

// A phone, where the docked contents column does not fit and its two stand-ins appear.
test.use({ viewport: { width: 390, height: 844 } });

test("on a phone the contents open as a drawer, and close once something is opened", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await expect(page.locator(".contents-column.docked")).toBeHidden();

  await page.getByTestId("open-contents").click();
  const drawer = page.getByRole("dialog", { name: "Contents" });
  await expect(drawer).toBeVisible();

  await drawer.locator(".tree-row", { hasText: "Billing" }).first().click();

  await expect(drawer).toBeHidden();
  await expect(page.getByTestId("folder-name")).toHaveText("Billing");
});

test("on a phone search has a button of its own", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await page.getByTestId("phone-search").click();

  await expect(page.getByTestId("search")).toBeVisible();
  await expect(page.getByTestId("search-go")).toBeVisible();
});
