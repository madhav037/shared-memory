import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("an author retires their own memory, and it stays readable for the record", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Release notes go out on Thursday");
  await expect(page.getByTestId("in-force")).toContainText("It holds for everyone on Billing");

  await page.getByTestId("retire").click();
  await page.getByTestId("retire-confirm").click();

  // The margin's actions go with the memory the moment it is no longer active, so the banner is what is left.
  await expect(page.getByTestId("retired-banner")).toContainText("no longer true");
  await expect(page.getByTestId("retired-banner")).toContainText("stays for the record");
  await expect(page.getByTestId("memory-body")).toContainText("Wednesday release train");
  await expect(page.getByTestId("in-force")).toHaveCount(0);
});

test("retiring a memory someone else wrote asks its author instead", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Gotchas", "The API rate limit is 100 a minute");

  await page.getByTestId("retire").click();
  await page.getByTestId("retire-confirm").click();

  await expect(page.getByTestId("retired")).toContainText("Raj Raiser has been asked to retire it");
  await expect(page.getByTestId("open-challenges")).toContainText("Olive Owner wants to retire it");
  await expect(page.getByTestId("open-challenges")).toContainText("Until Raj Raiser decides, it stands as it is");
  await expect(page.getByTestId("retired-banner")).toHaveCount(0);

  await signInAs(page, 2, "dana");
  await page.getByTestId("to-challenges").click();
  await expect(page.getByTestId("waiting")).toContainText("Olive Owner wants to retire it");
  await expect(page.getByTestId("waiting").getByTestId("reasoning")).toHaveCount(0);
});
