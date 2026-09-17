import { expect, test } from "@playwright/test";

test("a member sees a memory's versions and what changed between them", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await page.getByTestId("projects").getByRole("link", { name: "Billing" }).click();
  await page.getByRole("link", { name: "Use pnpm, not npm" }).first().click();

  const versions = page.getByTestId("history").locator("> div");
  await expect(versions.first()).toContainText("Promote");

  await versions.first().getByRole("button", { name: "Read it" }).click();

  await expect(page.getByTestId("version-text")).toContainText("second lockfile");
});
