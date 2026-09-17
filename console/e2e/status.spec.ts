import { expect, test } from "@playwright/test";

test("the console shows that it reached the server and offers to sign in", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Shared Memory" })).toBeVisible();
  await expect(page.getByTestId("status")).toContainText(/connected to the shared memory server/i);
  await expect(page.getByTestId("sign-in")).toBeVisible();
});

test("the console says so when it cannot reach the server", async ({ page }) => {
  await page.route("**/api/status", (route) => route.abort());

  await page.goto("/");

  await expect(page.getByTestId("status")).toContainText(/can’t reach the server/i);
});
