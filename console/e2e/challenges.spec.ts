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

  const reasoning = dispute.getByTestId("reasoning");
  await expect(reasoning).toContainText("Reasoning");
  await expect(reasoning.getByTestId("reasoning-text")).toHaveText(
    "The reset moved to 02:17 UTC when the nightly backup took *midnight*.",
  );
  await expect(reasoning.locator("em, strong")).toHaveCount(0);
  await expect(dispute.locator('[data-testid="reasoning"] ~ [data-testid="facing"]')).toHaveCount(1);

  // An offer is marked up the way a memory's history is: what it puts in, bracketed and keyed to a note saying
  // what it took out. Without the marks it reads in its own words.
  await expect(dispute.getByTestId("amended").locator("ins")).toContainText("02:17 UTC");
  await expect(dispute.getByRole("list", { name: "Amendments" })).toContainText(
    "Words substituted by this offer, in place of night.",
  );
  await page.getByLabel("Show what each offer takes out and puts in").uncheck();
  await expect(dispute.getByTestId("amended")).toHaveCount(0);
  await expect(dispute.getByTestId("facing-text").last()).toContainText("every night at 02:17 UTC");
  await dispute.getByRole("button", { name: "Accept: supersede it" }).click();
  await expect(page.getByTestId("nothing-waiting")).toBeVisible();

  await openInContents(page, "Billing", "Project memory", "Gotchas", "Staging resets nightly");
  await expect(page.getByTestId("superseded-by")).toBeVisible();
  await expect(page.getByTestId("superseded-by")).toContainText("staging-resets-at-02-17-utc");
});

test("a member sees the challenges they raised, their Reasoning, and how each ended", async ({ page }) => {
  await signInAs(page, 2, "dana");
  await page.getByTestId("to-challenges").click();

  await expect(page.getByTestId("raised")).toContainText("to supersede it");
  await expect(page.getByTestId("raised-reasoning")).toContainText("when the nightly backup took *midnight*.");
  await expect(page.getByTestId("raised")).toContainText("Accepted");
  await expect(page.getByTestId("nothing-waiting")).toBeVisible();
});
