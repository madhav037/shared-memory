import { expect, test } from "@playwright/test";

test("a member pins a memory, sees it in the project's pins, and unpins it", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await page.getByTestId("projects").getByRole("link", { name: "Billing" }).click();
  await page.getByRole("link", { name: "Use pnpm, not npm" }).first().click();

  await page.getByTestId("pin").click();
  await expect(page.getByTestId("pinned")).toBeVisible();

  await page.goBack();
  const pins = page.getByTestId("pins");
  await expect(pins).toContainText("Use pnpm, not npm");
  await expect(pins).toContainText("tokens");

  await pins.getByTestId("unpin-memory").click();
  await expect(page.getByTestId("pins")).toHaveCount(0);
});
