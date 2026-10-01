import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

// Lena leads Reporting. Wes wrote "Reports are built at 06:00" there and Olive, the team's owner, has challenged it.
// Olive raised it, so it isn't hers to decide as an admin; Lena wrote neither memory, and it is hers as a lead.

test("a project lead decides a challenge against another member's memory, and the audit log says in what capacity", async ({
  page,
}) => {
  await signInAs(page, 79, "lena");
  await expect(page.getByTestId("waiting")).toContainText("Olive Owner wants to supersede it");

  await page.getByTestId("decide-them").click();
  const dispute = page.getByTestId("waiting");
  await expect(dispute).toContainText("As it stands now, by Wes Writer (emp-wes)");
  await expect(dispute.getByTestId("decides-as")).toContainText("yours to decide as a project lead");
  await expect(dispute.getByTestId("reasoning-text")).toHaveText("Finance starts an hour earlier since June.");

  await dispute.getByRole("button", { name: "Accept: supersede it" }).click();
  await expect(page.getByTestId("nothing-waiting")).toBeVisible();

  // A lead reads the audit log of the projects they lead: the decision is there, with the capacity it was made in.
  await page.getByTestId("to-audit").click();
  const decided = page.getByTestId("audit-table").locator("tbody tr", { hasText: "Challenge decided" });
  await expect(decided).toContainText("Lena Lead");
  await expect(decided).toContainText("accepted");
  await expect(decided).toContainText("Decided as a project lead");
});
