import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

// Tess leads Payments. Wes wrote "Refunds are allowed for 14 days" there; Olive's session says it contradicts the code,
// and Raj's joined that doubt as a +1 with a line of its own. Olive raised it, so it is Tess's to decide as a lead. The
// two journeys run in this order on purpose: rejecting the doubt takes the mark away, and the first one needs it.

const REFUNDS = "Refunds are allowed for 14 days";

test("a memory view shows the in-doubt mark and links to the memory's open doubts", async ({ page }) => {
  await signInAs(page, 81, "tess");
  await openInContents(page, "Payments", "Project memory", "Gotchas", REFUNDS);

  await expect(page.getByTestId("memory-details").getByTestId("in-doubt-mark")).toHaveText("In doubt");
  const inDoubt = page.getByTestId("in-doubt");
  await expect(inDoubt).toContainText(
    "In doubt. 2 say it contradicts payments-api:src/refunds.py:18, payments-api:src/support/policy.py:7.",
  );
  // A doubt is said once, in the in-doubt line, not again as a request to supersede it.
  await expect(page.getByTestId("open-challenges")).toHaveCount(0);

  await inDoubt.getByRole("link", { name: "See its open doubts and decide" }).click();
  await expect(page).toHaveURL(/\/challenges\?path=/);
  await expect(page.getByTestId("showing-one")).toContainText("Only the challenges against one memory.");
  const dispute = page.getByTestId("waiting");
  await expect(dispute.getByRole("heading", { name: REFUNDS })).toBeVisible();
  await expect(dispute.getByTestId("doubt-reason")).toHaveText("Contradicts the code");
});

test("a lead sees a doubt with its +1s and evidence on the challenges page, rejects it, and the memory's in-doubt mark goes", async ({
  page,
}) => {
  await signInAs(page, 81, "tess");
  await expect(page.getByTestId("waiting")).toContainText("Olive Owner doubts it: contradicts the code");

  await page.getByTestId("decide-them").click();
  const dispute = page.getByTestId("waiting");
  await expect(dispute.getByTestId("doubt-reason")).toHaveText("Contradicts the code");
  await expect(dispute.getByTestId("doubt-count")).toHaveText("+1");
  await expect(dispute.getByTestId("decides-as")).toContainText("yours to decide as a project lead");

  // Every raise's evidence, the first raiser's first: who, why, and the file and line it quotes.
  const evidence = dispute.getByTestId("evidence-entry");
  await expect(evidence).toHaveCount(2);
  await expect(evidence.first()).toContainText("Olive Owner");
  await expect(evidence.first()).toContainText("The refund window in the code is 30 days.");
  await expect(evidence.first().getByTestId("evidence-reference")).toHaveText("payments-api:src/refunds.py:18");
  await expect(evidence.first()).toContainText("REFUND_WINDOW_DAYS = 30");
  await expect(evidence.last()).toContainText("Raj Raiser");
  await expect(evidence.last()).toContainText("Support approved a refund on day 20 yesterday.");
  await expect(evidence.last().getByTestId("evidence-reference")).toHaveText("payments-api:src/support/policy.py:7");

  await dispute.getByRole("button", { name: "Reject: keep it as it is" }).click();
  const slip = page.getByTestId("decided");
  await expect(slip).toContainText(`You rejected it. ‘${REFUNDS}’ stays as it is.`);

  await slip.getByRole("link", { name: "Read it" }).click();
  await expect(page.getByTestId("memory-title")).toContainText(REFUNDS);
  await expect(page.getByTestId("in-force")).toBeVisible();
  await expect(page.getByTestId("in-doubt")).toHaveCount(0);
  await expect(page.getByTestId("in-doubt-mark")).toHaveCount(0);
});
