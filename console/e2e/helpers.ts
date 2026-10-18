import { expect, type Page } from "@playwright/test";

/** The fake GitHub the journey server starts; tests/console_e2e_server.py reads the same variable, with the same default. */
export const fakeGitHub = `http://127.0.0.1:${process.env.SHARED_MEMORY_E2E_GITHUB_PORT ?? "8126"}`;

/** Sign in as this GitHub account, through the fake GitHub the journeys run against. */
export async function signInAs(page: Page, id: number, login: string) {
  await page.request.post(`${fakeGitHub}/as-account`, { data: { id, login } });
  await page.goto("/");
  await page.getByTestId("sign-in").click();
  // The member menu, not their name: the name is hidden at phone width, the menu is there at every width.
  await expect(page.getByTestId("member-menu")).toBeVisible();
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

/** Choose a coding agent from the page's one "Agent" select, on Settings or Connect your agent. */
export async function chooseAgent(page: Page, name: string) {
  await page.getByTestId("agent-choice").click();
  await page.getByRole("option", { name, exact: true }).click();
}
