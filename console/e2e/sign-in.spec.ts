import { expect, test } from "@playwright/test";

const fakeGitHub = "http://127.0.0.1:8124";

/** Whoever signs in next is this GitHub account. */
async function gitHubAccountIs(request: { post: (url: string, options: object) => Promise<unknown> }, id: number, login: string) {
  await request.post(`${fakeGitHub}/as-account`, { data: { id, login } });
}

test("a member signs in with GitHub, sees who they are, and signs out", async ({ page }) => {
  await gitHubAccountIs(page.request, 1, "olive");

  await page.goto("/");
  await page.getByTestId("sign-in").click();

  await expect(page.getByTestId("status")).toContainText("Signed in as Olive Owner (E1001), owner of team acme");

  await page.getByTestId("sign-out").click();

  await expect(page.getByTestId("sign-in")).toBeVisible();
});

test("a GitHub account nobody has linked is turned away", async ({ page }) => {
  await gitHubAccountIs(page.request, 999, "a-stranger");

  await page.goto("/");
  await page.getByTestId("sign-in").click();

  await expect(page.getByTestId("sign-in-error")).toContainText("isn't linked to a member");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});
