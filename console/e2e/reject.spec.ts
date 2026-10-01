import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

// Mira wrote "How Billing is built"; Olive has offered a version of it that moves the queue. Both memories set
// their parts out as a list, so the console can say what accepting would change part by part. The two journeys
// run in this order on purpose: rejecting closes the challenge, and the first one needs it open.

test("an offered memory says whose it is and that it is waiting on its author", async ({ page }) => {
  await signInAs(page, 3, "mira");
  await expect(page.getByTestId("waiting")).toContainText("Olive Owner wants to supersede it");

  await page.getByTestId("decide-them").click();
  await page.getByRole("link", { name: "How Billing is built now" }).click();

  await expect(page.getByTestId("personal-banner")).toContainText("Personal memory of Olive Owner");
  await expect(page.getByTestId("pending")).toContainText("Waiting on a challenge");
  await expect(page.getByTestId("pending")).toContainText("its author, a project lead or an admin decides");
});

test("a member reads what a challenge would change and rejects it, and the memory stands", async ({ page }) => {
  await signInAs(page, 3, "mira");
  await page.getByTestId("decide-them").click();

  // Word-by-word marking reads as noise across two separately written memories; parts can be said outright.
  const changes = page.getByTestId("what-changes");
  await expect(changes).toContainText("here is what would be different");
  await expect(changes).toContainText("Queue");
  await expect(changes).toContainText("RabbitMQ");
  await expect(changes).toContainText("Kafka");
  await expect(changes).toContainText("Unchanged: Language, Database.");
  await expect(page.getByTestId("reasoning-text")).toHaveText("Billing moved its queue to Kafka in March.");
  await expect(page.locator('[data-testid="reasoning"] ~ [data-testid="what-changes"]')).toHaveCount(1);

  await page.getByRole("button", { name: "Reject: keep it as it is" }).click();
  await expect(page.getByTestId("nothing-waiting")).toBeVisible();

  await openInContents(page, "Billing", "Project memory", "Decisions", "How Billing is built");
  await expect(page.getByTestId("in-force")).toBeVisible();
  await expect(page.getByTestId("memory-body")).toContainText("RabbitMQ");
  await expect(page.getByTestId("superseded-by")).toHaveCount(0);
});
