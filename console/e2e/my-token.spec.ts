import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a member issues their own personal token and sees it once", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("member-menu").click();
  await page.getByTestId("to-my-token").click();

  await expect(page.getByRole("heading", { name: "Connect your agent" })).toBeVisible();
  await page.getByTestId("issue-token").click();
  await page.getByTestId("issue-token-confirm").click();

  const shown = page.getByTestId("token-value");
  await expect(shown).toContainText("smt_");
  const token = await shown.textContent();

  await page.reload();

  await expect(page.getByTestId("issue-token")).toBeVisible();
  await expect(page.getByTestId("issued-token")).toBeHidden();
  expect(await page.content()).not.toContain(token ?? "never");
});
