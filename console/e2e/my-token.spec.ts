import { expect, test } from "@playwright/test";

test("a member issues their own personal token and sees it once", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await page.getByTestId("to-my-token").click();

  await expect(page.getByText("Connect your Claude Code")).toBeVisible();
  await page.getByTestId("issue-token").click();

  const shown = page.getByTestId("token-value");
  await expect(shown).toContainText("smt_");
  const token = await shown.textContent();

  await page.reload();

  await expect(page.getByTestId("issue-token")).toBeVisible();
  await expect(page.getByTestId("issued-token")).toBeHidden();
  expect(await page.content()).not.toContain(token ?? "never");
});
