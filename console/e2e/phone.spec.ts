import { expect, type Page, test } from "@playwright/test";

import { signInAs } from "./helpers";

// A phone, where the docked contents column does not fit and its two stand-ins appear.
test.use({ viewport: { width: 390, height: 844 } });

test("on a phone the contents open as a drawer, and close once something is opened", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await expect(page.locator(".contents-column.docked")).toBeHidden();

  await page.getByTestId("open-contents").click();
  const drawer = page.getByRole("dialog", { name: "Contents" });
  await expect(drawer).toBeVisible();

  await drawer.locator(".tree-row", { hasText: "Billing" }).first().click();

  await expect(drawer).toBeHidden();
  await expect(page.getByTestId("folder-name")).toHaveText("Billing");
});

test("on a phone search has a button of its own", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await page.getByTestId("phone-search").click();

  await expect(page.getByTestId("search")).toBeVisible();
  await expect(page.getByTestId("search-go")).toBeVisible();
});

test("on a phone the waiting challenges stay counted in the band, and the menu says it holds the pages", async ({
  page,
}) => {
  // Mira has a challenge waiting on her memory until reject.spec.ts closes it; Olive's is decided before this runs.
  await signInAs(page, 3, "mira");

  // With the nav folded into the menu, the menu's button still counts what waits for her, and says so by name.
  const menu = page.getByTestId("member-menu");
  await expect(page.getByTestId("phone-waiting")).toBeVisible();
  await expect(page.getByTestId("phone-waiting")).toHaveText(/^[1-9]\d*$/);
  await expect(menu).toHaveAccessibleName(/the console's pages, .*\d+ challenges? waiting$/);

  await menu.click();
  await page.getByRole("menuitem", { name: /Challenges/ }).click();
  await expect(page).toHaveURL(/\/challenges$/);
});

test("on a phone the contents button says Contents, so it can't pass for the menu beside it", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await expect(page.getByTestId("open-contents")).toHaveText("Contents");
});

/** Every cell of a register's first row fits the phone's width, and its first cell has the width to itself. */
async function expectStacked(page: Page, register: string) {
  const row = page.getByTestId(register).locator("tbody tr").first();
  await expect(row).toBeVisible();
  for (const cell of await row.locator("td").all()) {
    const box = await cell.boundingBox();
    if (box && box.width > 0) expect(box.x + box.width).toBeLessThanOrEqual(390);
  }
  const primary = await row.locator("td.primary").boundingBox();
  expect(primary?.width ?? 0).toBeGreaterThan(200);
  // The column heads stay for a screen reader, out of sight.
  expect((await page.getByTestId(register).locator("thead").boundingBox())?.height ?? 0).toBeLessThanOrEqual(1);
}

test("on a phone the registers set each row out as an entry the width of the page", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await page.goto("/audit");
  await expectStacked(page, "audit-table");

  await page.goto("/team");
  await expectStacked(page, "members");

  await page.goto("/challenges");
  await expectStacked(page, "raised");
});

test("on a phone the band fits the narrowest screen", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await signInAs(page, 1, "olive");

  await expect(page.getByTestId("open-contents")).toHaveText("Contents");
  const right = await page.locator(".masthead-end").evaluate((end) => end.getBoundingClientRect().right);
  expect(right).toBeLessThanOrEqual(320);
});

test("on a phone the audit log says how much of it is shown, and pages older changes in", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.goto("/audit");

  await expect(page.getByTestId("audit-showing")).toHaveText(/^Showing (the latest 20|all \d+) changes\.$/);
  expect(await page.getByTestId("audit-table").locator("tbody tr").count()).toBeLessThanOrEqual(20);
});

test("on a phone the board says how many of its columns are in view, and which lie sideways", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByRole("link", { name: "Board" }).first().click();

  await expect(page.getByTestId("board-swipe")).toHaveText("1 of 4 columns in view. Swipe for Doing, Blocked and Done.");
  await page.getByTestId("board").evaluate((board) => (board.scrollLeft = board.scrollWidth));
  await expect(page.getByTestId("board-swipe")).toContainText("Swipe for To do");
});

test("on a phone the board's filters sit in rows: the view and Add card, the assignee, then label and priority", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByRole("link", { name: "Board" }).first().click();

  const top = async (testid: string) => (await page.getByTestId(testid).boundingBox())?.y ?? -1;
  const bottom = async (testid: string) => {
    const box = await page.getByTestId(testid).boundingBox();
    return box ? box.y + box.height : -1;
  };
  expect(Math.abs((await bottom("board-view")) - (await bottom("add-card")))).toBeLessThan(4);
  expect(await top("filter-assignee")).toBeGreaterThan(await bottom("add-card"));
  expect(Math.abs((await top("filter-label")) - (await top("filter-priority")))).toBeLessThan(4);
  expect(await top("filter-label")).toBeGreaterThan(await bottom("filter-assignee"));
});
