import { expect, test, type Page } from "@playwright/test";

import { signInAs, signOut } from "./helpers";

const fromConsole = { "X-Shared-Memory-Console": "1" };

/**
 * These journeys change a board, so they have one of their own: Checkout, made the first time one of them asks for it.
 * Billing's board stays as the server seeded it, for the journeys that only read it.
 */
async function checkout(page: Page): Promise<string> {
  await signInAs(page, 1, "olive");
  const listed = (await (await page.request.get("/api/projects")).json()) as {
    projects: { project_id: string; name: string }[];
  };
  const found = listed.projects.find((one) => one.name === "Checkout");
  if (found) return found.project_id;
  const made = await page.request.post("/api/projects", { headers: fromConsole, data: { name: "Checkout" } });
  return ((await made.json()) as { project_id: string }).project_id;
}

/** A card for a journey to change, added the way the console adds one; its number comes back. */
async function card(page: Page, project: string, title: string): Promise<number> {
  const added = await page.request.post(`/api/projects/${project}/cards`, { headers: fromConsole, data: { title } });
  expect(added.ok()).toBeTruthy();
  return ((await added.json()) as { number: number }).number;
}

async function openBoard(page: Page, project: string) {
  await page.goto(`/projects/${project}/board`);
  await expect(page.getByTestId("board")).toBeVisible();
}

function column(page: Page, name: string) {
  return page.getByTestId(`column-${name}`);
}

function tile(page: Page, title: string) {
  return page.getByTestId("card").filter({ hasText: title });
}

test("a member adds a card, and it lands in To do", async ({ page }) => {
  const project = await checkout(page);
  await openBoard(page, project);

  await page.getByTestId("add-card").click();
  await page.getByTestId("card-title").fill("Charge the saved card");
  await page.getByTestId("card-description").fill("Customers with a saved card skip the payment form.");
  await page.getByTestId("card-form-submit").click();

  await expect(column(page, "to_do").getByTestId("card").filter({ hasText: "Charge the saved card" })).toBeVisible();
  await tile(page, "Charge the saved card").click();
  await expect(page.getByTestId("card-panel")).toContainText("Customers with a saved card skip the payment form.");
  await expect(page.getByTestId("card-panel")).toContainText("By Olive Owner");
});

test("a card is dragged to Doing, and reordered there", async ({ page }) => {
  const project = await checkout(page);
  await card(page, project, "Round tax per line");
  await card(page, project, "Round tax per order");
  await openBoard(page, project);
  const doing = column(page, "doing");

  // Dropped on the column, away from its cards, a card goes to the bottom.
  await tile(page, "Round tax per line").dragTo(doing.locator("h2"));
  await expect(doing.getByTestId("card").filter({ hasText: "Round tax per line" })).toBeVisible();
  await tile(page, "Round tax per order").dragTo(doing.locator("h2"));
  await expect(doing.getByTestId("card").filter({ hasText: "Round tax" })).toHaveText([/per line/, /per order/]);
  await expect(column(page, "to_do")).not.toContainText("Round tax");

  // Dropped on the upper half of another card, it goes above that card.
  await tile(page, "Round tax per order").dragTo(tile(page, "Round tax per line"), { targetPosition: { x: 24, y: 4 } });
  await expect(doing.getByTestId("card").filter({ hasText: "Round tax" })).toHaveText([/per order/, /per line/]);

  // The order is the board's, not the page's: it is still there when the board is read again.
  await page.reload();
  await expect(doing.getByTestId("card").filter({ hasText: "Round tax" })).toHaveText([/per order/, /per line/]);
});

test("a card dropped on Blocked asks what it is waiting for", async ({ page }) => {
  const project = await checkout(page);
  await card(page, project, "Refund to the original card");
  await openBoard(page, project);

  await tile(page, "Refund to the original card").dragTo(column(page, "blocked").locator("h2"));
  await page.getByTestId("blocked-reason").fill("The provider has not enabled refunds yet.");
  await page.getByTestId("blocked-submit").click();

  const blocked = column(page, "blocked").getByTestId("card").filter({ hasText: "Refund to the original card" });
  await expect(blocked).toContainText("The provider has not enabled refunds yet.");
});

test("a member claims a card and comments on it", async ({ page }) => {
  const project = await checkout(page);
  await card(page, project, "Email the receipt");
  await openBoard(page, project);

  await tile(page, "Email the receipt").click();
  const panel = page.getByTestId("card-panel");
  await panel.getByTestId("claim-card").click();

  await expect(panel.locator(".card-fields")).toContainText("Doing");
  await expect(panel.locator(".card-fields")).toContainText("Olive Owner");
  await expect(panel.getByTestId("claim-card")).toHaveCount(0);

  await panel.getByTestId("comment-text").fill("The template is in the design folder.");
  await panel.getByTestId("comment-send").click();
  await expect(panel.getByTestId("card-comments")).toContainText("The template is in the design folder.");
  await expect(panel.getByTestId("comment-text")).toHaveValue("");

  await page.keyboard.press("Escape");
  const claimed = column(page, "doing").getByTestId("card").filter({ hasText: "Email the receipt" });
  await expect(claimed).toContainText("Olive Owner");
});

test("a card is deleted once the member confirms", async ({ page }) => {
  const project = await checkout(page);
  await card(page, project, "Remove the old coupon field");
  await openBoard(page, project);

  await tile(page, "Remove the old coupon field").click();
  await page.getByTestId("delete-card").click();
  await page.getByTestId("delete-confirm").click();

  await expect(page.getByTestId("card-panel")).toHaveCount(0);
  await expect(page.getByTestId("board")).not.toContainText("Remove the old coupon field");
});

test("a change the member may not make is refused, and the board says why", async ({ page }) => {
  const project = await checkout(page);
  const number = await card(page, project, "Rotate the payment keys");
  const claimed = await page.request.post(`/api/projects/${project}/cards/${number}/claim`, { headers: fromConsole });
  expect(claimed.ok()).toBeTruthy();

  // Raj is neither the card's assignee nor a lead of Checkout.
  await signOut(page);
  await signInAs(page, 2, "dana");
  await openBoard(page, project);
  await tile(page, "Rotate the payment keys").dragTo(column(page, "done").locator("h2"));

  await expect(page.getByTestId("change-refused")).toContainText("Card " + number + " is assigned to");
  await expect(page.getByTestId("change-refused")).toContainText("Say what you want in a comment instead.");
  await expect(column(page, "doing").getByTestId("card").filter({ hasText: "Rotate the payment keys" })).toBeVisible();
});

test("a member links a card to a memory and a file, and takes a link off", async ({ page }) => {
  const project = await checkout(page);
  const found = (await (await page.request.get("/api/search?query=pnpm")).json()) as {
    results: { path: string; title: string }[];
  };
  const memory = found.results.find((one) => one.title === "Use pnpm, not npm")!.path;
  await openBoard(page, project);

  await page.getByTestId("add-card").click();
  await page.getByTestId("card-title").fill("Pin the pnpm version");
  await page.getByTestId("card-memory-links").fill(memory);
  await page.getByTestId("card-memory-links").press("Enter");
  await page.getByTestId("card-file-links").fill("checkout-web:package.json");
  await page.getByTestId("card-file-links").press("Enter");
  await page.getByTestId("card-form-submit").click();

  await tile(page, "Pin the pnpm version").click();
  const panel = page.getByTestId("card-panel");
  await expect(panel.getByTestId("card-memories")).toContainText("Use pnpm, not npm");
  await expect(panel.getByTestId("card-files")).toContainText("checkout-web");
  await expect(panel.getByTestId("card-files")).toContainText("package.json");

  // A file link the board can't keep is refused in its words, with what was typed left in place.
  await panel.getByTestId("edit-card").click();
  await page.getByTestId("card-file-links").fill("no-repository");
  await page.getByTestId("card-file-links").press("Enter");
  await page.getByTestId("card-form-submit").click();
  await expect(page.getByTestId("card-form-refused")).toContainText("must be written as repository:path");

  // Both file links come off again; the memory link stays.
  await page.getByTestId("card-file-links").press("Backspace");
  await page.getByTestId("card-file-links").press("Backspace");
  await page.getByTestId("card-form-submit").click();
  await expect(panel.getByTestId("card-memories")).toContainText("Use pnpm, not npm");
  await expect(panel.getByTestId("card-files")).toHaveCount(0);
});
