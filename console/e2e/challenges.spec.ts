import { expect, test } from "@playwright/test";

test("the owner decides a challenge waiting for them and the memory is superseded", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();

  // The console opens on what is waiting for this member.
  const waiting = page.getByTestId("waiting");
  await expect(waiting).toContainText("Staging resets nightly");
  await expect(waiting).toContainText("emp-dana wants to supersede it");
  await expect(waiting).toContainText("02:17 UTC");

  await waiting.getByRole("button", { name: "Accept" }).first().click();
  await expect(page.getByTestId("waiting")).toHaveCount(0);

  await page.getByTestId("projects").getByRole("link", { name: "Billing" }).click();
  await page.getByRole("link", { name: "Staging resets nightly" }).first().click();

  await expect(page.getByTestId("superseded-by")).toBeVisible();
  await expect(page.getByTestId("superseded-by")).toContainText("staging-resets-at-02-17-utc");
});

test("a member sees the challenges they raised and how each ended", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 2, login: "dana" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await page.getByTestId("to-challenges").click();

  await expect(page.getByTestId("raised")).toContainText("to supersede it");
  await expect(page.getByTestId("raised")).toContainText("accepted");
  await expect(page.getByTestId("nothing-waiting")).toBeVisible();
});
