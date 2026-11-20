import { expect, test } from "@playwright/test";

import { fakeGitHub, signInAs, signOut } from "./helpers";

test("a member signs in with GitHub, sees who they are, and signs out", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await expect(page.getByTestId("who")).toHaveText("Olive Owner");
  await expect(page).toHaveTitle("Shared Memory");
  await page.getByTestId("member-menu").click();
  await expect(page.getByText("Olive Owner (E1001), owner of acme")).toBeVisible();
  await page.keyboard.press("Escape");

  await signOut(page);
  await expect(page.getByTestId("sign-in-page")).toBeVisible();
});

test("a visitor who isn't signed in lands on the sign-in at any address, with no landing page or plans", async ({
  page,
}) => {
  for (const address of ["/", "/company", "/search?q=retries", "/terms", "/coming-soon", "/no-such-page"]) {
    await page.goto(address);

    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in");
    await expect(page.getByTestId("sign-in")).toBeVisible();
    await expect(page.locator("#pricing")).toHaveCount(0);
    await expect(page.getByText(/every agent knows/i)).toHaveCount(0);
  }
  await expect(page).toHaveTitle("Shared Memory");
});

test("a server given no platform address links nowhere outside itself", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("sign-in")).toBeVisible();
  await expect(page.getByTestId("platform-links")).toHaveCount(0);

  await signInAs(page, 1, "olive");
  await expect(page.getByTestId("platform-links")).toHaveCount(0);
});

test("a signed-in member reaching an address the console doesn't have is told so", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await page.goto("/no-such-page");

  await expect(page.getByTestId("not-found")).toContainText("/no-such-page");
  await expect(page.getByTestId("member-menu")).toBeVisible();
});

test("a GitHub account nobody has linked is turned away", async ({ page }) => {
  await page.request.post(`${fakeGitHub}/as-account`, { data: { id: 999, login: "a-stranger" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();

  await expect(page.getByTestId("sign-in-error")).toContainText("isn't linked to a member");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});
