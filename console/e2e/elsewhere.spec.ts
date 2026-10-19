import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a plan's action that isn't built yet says it's coming soon, and leads back to the plans", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("plan-10").getByRole("link", { name: /Start a 7-day trial/ }).click();
  await expect(page).toHaveURL(/\/coming-soon\?for=trial$/);
  await expect(page.getByTestId("coming-soon")).toContainText("Trials on a server hosted by us aren’t open yet.");

  await page.getByRole("link", { name: /Back to the plans/ }).click();
  await expect(page.locator("#pricing")).toBeInViewport();

  await page.locator("#pricing").getByRole("radio", { name: "Self-hosted" }).click();
  await page.getByTestId("plan-5").getByRole("link", { name: /Get a license/ }).click();
  await expect(page.getByTestId("coming-soon")).toContainText("Licenses for self-hosted servers aren’t on sale yet.");
});

test("an address that isn't the console's is not found, while a console address still offers sign-in", async ({
  page,
}) => {
  await page.goto("/no-such-page");
  await expect(page.getByTestId("not-found")).toContainText("/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("There’s no page at this address.");

  await page.goto("/team");
  await expect(page.getByTestId("sign-in")).toBeVisible();
});

test("a signed-in member who follows a dead address is told so inside the console", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await page.goto("/no-such-page");
  await expect(page.getByTestId("not-found")).toContainText("/no-such-page");
  await expect(page.getByTestId("member-menu")).toBeVisible();
  await page.getByRole("link", { name: /Go to the front page/ }).click();
  await expect(page).toHaveURL(/\/$/);
});
