import { expect, test, type Page } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

async function openBoard(page: Page) {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing");
  await page.getByTestId("to-board").click();
  await expect(page.getByTestId("board")).toBeVisible();
}

function column(page: Page, name: string) {
  return page.getByTestId(`column-${name}`);
}

test("a project's board shows its cards in To do, Doing, Blocked and Done", async ({ page }) => {
  await openBoard(page);

  await expect(column(page, "to_do").getByTestId("card")).toHaveText([/Split the invoice module/]);
  await expect(column(page, "doing").getByTestId("card")).toHaveText([/Retry failed webhooks/]);
  await expect(column(page, "blocked").getByTestId("card")).toHaveText([/Upgrade the queue client/]);
  await expect(column(page, "blocked")).toContainText("Needs the new retry rules first.");
  await expect(column(page, "done").getByTestId("card")).toHaveText([/Drop the legacy exporter/]);
});

test("a card opens in a side panel with its links and comments", async ({ page }) => {
  await openBoard(page);

  await column(page, "doing").getByTestId("card").click();

  const panel = page.getByTestId("card-panel");
  await expect(panel).toContainText("Retry failed webhooks");
  await expect(panel).toContainText("Webhooks that fail are dropped.");
  await expect(panel).toContainText("Olive Owner");
  await expect(panel.getByTestId("card-memories")).toContainText("Use pnpm, not npm");
  await expect(panel.getByTestId("card-files")).toContainText("src/webhooks/retry.ts");
  await expect(panel.getByTestId("card-comments")).toContainText("Raj Raiser");
  await expect(panel.getByTestId("card-comments")).toContainText("The provider retries three times on its side too.");
  await expect(page).toHaveURL(/card=1/);

  // The card a blocked card waits on opens from the blocked card's panel.
  await page.goto(page.url().replace("card=1", "card=3"));
  await expect(panel).toContainText("Needs the new retry rules first.");
  await panel.getByTestId("waits-on").click();
  await expect(panel).toContainText("Retry failed webhooks");

  await panel.getByTestId("card-memories").getByRole("link", { name: "Use pnpm, not npm" }).click();
  await expect(page).toHaveURL(/\/memory\?path=/);
});

test("the board narrows by label, priority and assignee", async ({ page }) => {
  await openBoard(page);

  await page.getByTestId("filter-label").click();
  await page.getByRole("option", { name: "cleanup" }).click();
  await expect(page.getByTestId("card")).toHaveText([/Split the invoice module/, /Drop the legacy exporter/]);

  await page.getByTestId("filter-priority").click();
  await page.getByRole("option", { name: "Low" }).click();
  await expect(page.getByTestId("card")).toHaveText([/Split the invoice module/]);

  await page.getByTestId("clear-filters").click();
  await expect(page.getByTestId("card")).toHaveCount(4);
  await page.getByTestId("filter-assignee").click();
  await page.getByRole("option", { name: "Olive Owner" }).click();
  await expect(page.getByTestId("card")).toHaveText([/Retry failed webhooks/]);
});

test("the archive holds cards done more than 14 days ago", async ({ page }) => {
  await openBoard(page);
  await expect(page.getByTestId("board")).not.toContainText("Move receipts to the new template");

  await page.getByText("Archive", { exact: true }).click();

  const archive = page.getByTestId("archive");
  await expect(archive).toContainText("Move receipts to the new template");
  await expect(archive).not.toContainText("Drop the legacy exporter");
  await archive.getByText("Move receipts to the new template").click();
  await expect(page.getByTestId("card-panel")).toContainText("Done");
});

test("card changes are in the audit log, and a card there opens on its board", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-audit").click();

  await page.getByTestId("filter-kind").click();
  await page.getByRole("option", { name: "Card commented on" }).click();

  // Raj's is the one comment on Billing's board; other journeys comment on boards of their own.
  const rows = page.getByTestId("audit-table").locator("tbody tr").filter({ hasText: "Raj Raiser" });
  await expect(rows).toHaveCount(1);
  await rows.first().getByRole("link", { name: "Card 1" }).click();
  await expect(page.getByTestId("card-panel")).toContainText("Retry failed webhooks");
});
