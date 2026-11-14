import { expect, test, type Page } from "@playwright/test";

import { fakePlatform, hostedConsole, signOut } from "./helpers";

// The hosted server beside the journey server: its license key's last day was 31 August, the day before the journeys'
// clock, so it is read-only and stops on 14 September (#472, ADR-0022).
test.use({ baseURL: hostedConsole });

async function signInThroughThePlatform(page: Page, id: number, login: string) {
  await page.request.post(`${fakePlatform}/as-account`, { data: { id, login } });
  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await expect(page.getByTestId("member-menu")).toBeVisible();
}

test("an admin of a read-only hosted server sees until when and how to restore it, and inviting is refused; a member sees a plain notice", async ({
  page,
}) => {
  await signInThroughThePlatform(page, 1, "olive");

  const banner = page.getByTestId("license-banner");
  await expect(banner).toHaveAttribute("data-status", "read-only");
  await expect(banner).toContainText("This hosted server is read-only");
  await expect(banner).toContainText("lapsed on 2026-08-31");
  await expect(banner).toContainText("The server stops on 2026-09-14");
  await expect(banner).toContainText("paying for your team’s plan restores it");
  await expect(page.getByTestId("read-only-notice")).toHaveCount(0);

  // Inviting a member is refused with a plain answer, and nobody is added.
  await page.getByTestId("to-team").click();
  await page.getByTestId("new-member-id").fill("emp-late");
  await page.getByTestId("new-name").fill("Lee Late");
  await page.getByTestId("add-member").click();
  await expect(page.getByTestId("team-refused")).toContainText("read-only");
  await expect(page.getByTestId("new-member-token")).toHaveCount(0);

  await signOut(page);
  await signInThroughThePlatform(page, 2, "dana");

  await expect(page.getByTestId("read-only-notice")).toHaveText(
    "Memory can’t be changed right now: this server is read-only. You can still read and search everything.",
  );
  await expect(page.getByTestId("license-banner")).toHaveCount(0);
});
