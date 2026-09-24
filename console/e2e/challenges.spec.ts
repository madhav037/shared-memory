import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("the owner decides a challenge waiting for them and the memory is superseded", async ({ page }) => {
  await signInAs(page, 1, "olive");

  // The console opens on what is waiting for this member.
  const waiting = page.getByTestId("waiting");
  await expect(waiting).toContainText("Staging resets nightly");
  await expect(waiting).toContainText("Raj Raiser wants to supersede it");
  await expect(waiting).toContainText("02:17 UTC");

  await page.getByTestId("decide-them").click();
  const dispute = page.getByTestId("waiting");

  // An offer is shown in its own words. Marking up what it takes out and puts in is there for whoever wants it.
  await expect(dispute.getByTestId("tracked")).toHaveCount(0);
  await page.getByLabel("Show what each offer takes out and puts in").check();
  await expect(dispute.locator(".tracked-text del")).toContainText("every night.");
  await expect(dispute.locator(".tracked-text ins")).toContainText("02:17 UTC");
  await dispute.getByRole("button", { name: "Accept: supersede it" }).click();
  await expect(page.getByTestId("nothing-waiting")).toBeVisible();

  await openInContents(page, "Billing", "Project memory", "Gotchas", "Staging resets nightly");
  await expect(page.getByTestId("superseded-by")).toBeVisible();
  await expect(page.getByTestId("superseded-by")).toContainText("staging-resets-at-02-17-utc");
});

test("a member sees the challenges they raised and how each ended", async ({ page }) => {
  await signInAs(page, 2, "dana");
  await page.getByTestId("to-challenges").click();

  await expect(page.getByTestId("raised")).toContainText("to supersede it");
  await expect(page.getByTestId("raised")).toContainText("Accepted");
  await expect(page.getByTestId("nothing-waiting")).toBeVisible();
});
