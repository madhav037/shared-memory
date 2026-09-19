import { expect, test } from "@playwright/test";

import { signInAs, signOut } from "./helpers";

test("a member signs in with GitHub, sees who they are, and signs out", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await expect(page.getByTestId("who")).toHaveText("Olive Owner");
  await page.getByTestId("member-menu").click();
  await expect(page.getByText("Olive Owner (E1001), owner of acme")).toBeVisible();
  await page.keyboard.press("Escape");

  await signOut(page);
});

test("a GitHub account nobody has linked is turned away", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 999, login: "a-stranger" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();

  await expect(page.getByTestId("sign-in-error")).toContainText("isn't linked to a member");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});
