import { expect, test } from "@playwright/test";

test("a member opens a project, reads a memory, and finds it by searching", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();

  await page.getByTestId("projects").getByRole("link", { name: "Billing" }).click();
  await page.getByRole("link", { name: "Use pnpm, not npm" }).first().click();

  await expect(page.getByTestId("memory-title")).toHaveText("Use pnpm, not npm");
  await expect(page.getByTestId("memory-body")).toContainText("second lockfile");

  await page.goBack();
  await page.getByTestId("search").fill("which package manager do we use");

  await expect(page.getByTestId("results")).toContainText("Use pnpm, not npm");
  await expect(page.getByTestId("results")).toContainText("project memory");
});
