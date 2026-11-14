import { expect, test, type Page } from "@playwright/test";

import { fakePlatform, hostedConsole, signOut } from "./helpers";

// A hosted server: no GitHub app of its own, so the platform signs the member in and hands the sign-in over (#471).
test.use({ baseURL: hostedConsole });

/** Whoever the fake platform signs in next, and how that one sign-in goes wrong, if it does. */
async function platformSignsIn(
  page: Page,
  account: { id: number; login: string; subdomain?: string; expired?: boolean; forged?: boolean },
) {
  await page.request.post(`${fakePlatform}/as-account`, { data: account });
}

async function chooseToSignIn(page: Page) {
  await page.goto("/");
  await page.getByTestId("sign-in").click();
}

test("a member of a hosted server signs in through the platform", async ({ page }) => {
  await platformSignsIn(page, { id: 1, login: "olive" });

  await chooseToSignIn(page);

  await expect(page.getByTestId("member-menu")).toBeVisible();
  await page.getByTestId("member-menu").click();
  await expect(page.getByText("Olive Owner (E1001), owner of acme")).toBeVisible();
});

test("a sign-in whose signature doesn't check out is turned away", async ({ page }) => {
  await platformSignsIn(page, { id: 1, login: "olive", forged: true });

  await chooseToSignIn(page);

  await expect(page.getByTestId("sign-in-error")).toContainText("couldn't be checked");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});

test("a sign-in for another team's server is turned away", async ({ page }) => {
  await platformSignsIn(page, { id: 1, login: "olive", subdomain: "globex" });

  await chooseToSignIn(page);

  await expect(page.getByTestId("sign-in-error")).toContainText("for another team's server");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});

test("a sign-in that has expired is turned away", async ({ page }) => {
  await platformSignsIn(page, { id: 1, login: "olive", expired: true });

  await chooseToSignIn(page);

  await expect(page.getByTestId("sign-in-error")).toContainText("took too long");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});

test("a sign-in already used once is turned away", async ({ page }) => {
  await platformSignsIn(page, { id: 1, login: "olive" });
  await chooseToSignIn(page);
  await expect(page.getByTestId("member-menu")).toBeVisible();
  const handedBack: { url: string } = await (await page.request.get(`${fakePlatform}/last`)).json();
  await signOut(page);

  await page.goto(handedBack.url);

  await expect(page.getByTestId("sign-in-error")).toContainText("already used");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});

test("a GitHub account nobody has linked is turned away, as GitHub sign-in turns it away", async ({ page }) => {
  await platformSignsIn(page, { id: 999, login: "a-stranger" });

  await chooseToSignIn(page);

  await expect(page.getByTestId("sign-in-error")).toContainText("isn't linked to a member");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});
