import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("the Terms and the Privacy Policy render signed out, each marked as a draft", async ({ page }) => {
  await page.goto("/terms");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Terms of Service");
  await expect(page.getByTestId("legal-draft")).toContainText("Draft, pending legal review");
  await expect(page.getByTestId("legal-page")).toContainText("Madhav Lehru");

  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy Policy");
  await expect(page.getByTestId("legal-draft")).toContainText("Draft, pending legal review");
  await expect(page.getByTestId("legal-page")).toContainText("only one cookie");
});

test("the landing page's footer reaches both pages, and sign-in points to them", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("sign-in-notice")).toContainText("Terms");

  await page.getByTestId("legal-links").getByRole("link", { name: "Terms" }).click();
  await expect(page).toHaveURL(/\/terms$/);
  await page.getByTestId("legal-links").getByRole("link", { name: "Privacy" }).click();
  await expect(page).toHaveURL(/\/privacy$/);
});

test("coming soon and not found carry the footer links", async ({ page }) => {
  await page.goto("/coming-soon");
  await expect(page.getByTestId("legal-links")).toBeVisible();
  await page.goto("/no-such-page");
  await expect(page.getByTestId("legal-links")).toBeVisible();
});

test("a signed-in member finds the footer links in the console", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("legal-links").getByRole("link", { name: "Privacy" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy Policy");
  await expect(page.getByTestId("member-menu")).toBeVisible();
});
