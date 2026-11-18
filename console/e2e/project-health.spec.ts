import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

// Tess leads Payments. Olive's session and Tess's doubt Wes's "Payouts settle in two days" (tests/console_e2e_server.py);
// both raised it, so it waits on nobody's challenges page but its author's, and stays in doubt whatever order the
// journeys run in. No coding agent has used Wes's "Reports render through wkhtmltopdf", in Reporting, for 61 days.
// Tess's session in Payments edited src/payouts/schedule.py three times and src/payouts/retry.py once; no memory is tied
// to either.

const PAYOUTS = "Payouts settle in two days";

test("a lead opens project health from project settings, sees its coverage gaps and clicks through from a doubted memory to its challenge", async ({
  page,
}) => {
  await signInAs(page, 81, "tess");
  await page.getByTestId("project-card").filter({ hasText: "Payments" }).getByRole("link", { name: "Settings" }).click();
  await expect(page.getByTestId("project-name")).toHaveText("Payments");

  await page.getByTestId("to-health").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Project health");
  await expect(page.getByTestId("project-name")).toHaveText("Payments");
  await expect(page.getByTestId("possibly-outdated").getByTestId("nothing")).toBeVisible();

  const doubted = page.getByTestId("doubted-memory").filter({ hasText: PAYOUTS });
  await expect(doubted.getByTestId("doubt-line")).toHaveText("In doubt: 2 say it misled them.");
  await expect(doubted.getByTestId("doubt-count")).toHaveText("Doubted by 2 members");
  await expect(doubted.getByTestId("doubt-reason")).toHaveText("Misled a session: 2");
  const gaps = page.getByTestId("coverage-gap");
  await expect(gaps.getByTestId("gap-file")).toHaveText([
    "payments-api:src/payouts/schedule.py",
    "payments-api:src/payouts/retry.py",
  ]);
  await expect(gaps.getByTestId("gap-edits")).toHaveText(["Edited 3 times", "Edited 1 time"]);
  await expect(page.locator("main")).toContainText("in the last 30 days");
  // Read-only: nothing on the page pins, retires or decides.
  await expect(page.locator("main button")).toHaveCount(0);

  await doubted.getByRole("link", { name: "See its challenges" }).click();
  await expect(page).toHaveURL(/\/challenges\?path=/);
  await expect(page.getByTestId("showing-one")).toContainText("Only the challenges against one memory.");
  const doubt = page.getByTestId("others-doubt");
  await expect(doubt.getByTestId("doubt-reason")).toHaveText("Misled a session");
  await expect(doubt.getByTestId("doubt-count")).toHaveText("+1");
});

test("an admin sees a project's possibly outdated memory on its project health", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("project-card").filter({ hasText: "Reporting" }).getByRole("link", { name: "Settings" }).click();
  await page.getByTestId("to-health").click();

  const outdated = page.getByTestId("outdated-memory").filter({ hasText: "Reports render through wkhtmltopdf" });
  await expect(outdated.getByTestId("outdated-mark")).toHaveText("Possibly outdated");
  await expect(page.locator("main")).toContainText("for 60 days or more");
  await outdated.getByRole("link", { name: "Reports render through wkhtmltopdf" }).click();
  await expect(page.getByTestId("possibly-outdated")).toContainText("Possibly outdated.");
});

test("a member who is not a lead sees no project health link", async ({ page }) => {
  await signInAs(page, 2, "dana");
  await page.getByTestId("project-card").filter({ hasText: "Billing" }).getByRole("link", { name: "Settings" }).click();

  await expect(page.getByTestId("read-only")).toBeVisible();
  await expect(page.getByTestId("to-health")).toHaveCount(0);
});
