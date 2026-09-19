import { expect, type Page } from "@playwright/test";

const fakeGitHub = "http://127.0.0.1:8124";

/** Sign in as this GitHub account, through the fake GitHub the journeys run against. */
export async function signInAs(page: Page, id: number, login: string) {
  await page.request.post(`${fakeGitHub}/as-account`, { data: { id, login } });
  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await expect(page.getByTestId("who")).toBeVisible();
}

/** Sign out from the member menu in the masthead. */
export async function signOut(page: Page) {
  await page.getByTestId("member-menu").click();
  await page.getByTestId("sign-out").click();
  await expect(page.getByTestId("sign-in")).toBeVisible();
}

/** Open a folder or memory from the contents column by its name, top to bottom. */
export async function openInContents(page: Page, ...names: string[]) {
  for (const name of names) {
    await page.locator(".contents-column .tree-row", { hasText: name }).first().click();
  }
}
