import { expect, test } from "@playwright/test";

import { signInAs, signOut } from "./helpers";
import { signLicense } from "./license";

// The journey server's clock stands at 1 September 2026.
const KEY = signLicense({
  team: "Acme Billing",
  member_cap: 12,
  issued: "2026-09-01",
  expires: "2026-09-15",
  key_id: "acme-journey",
});

test("an admin sees the unlicensed banner, installs a key and sees the team, cap and expiry; a member can't", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-team").click();
  await expect(page.getByTestId("license-banner")).toBeVisible();

  // Anything that isn't a trustworthy key is refused, and nothing is installed.
  await page.getByTestId("license-key").fill("sm1.not.a-key");
  await page.getByTestId("install-license").click();
  await expect(page.getByTestId("team-refused")).toBeVisible();

  await page.getByTestId("license-key").fill(KEY);
  await page.getByTestId("install-license").click();

  await expect(page.getByTestId("license-team")).toHaveText("Acme Billing");
  await expect(page.getByTestId("license-cap")).toHaveText("12");
  await expect(page.getByTestId("license-expires")).toHaveText("2026-09-15");
  await expect(page.getByTestId("license-banner")).toContainText("expires on 2026-09-15");
  await expect(page.getByTestId("member-places")).toContainText("places used");

  // A member who isn't an admin sees the license but has nothing to install it with, and the server refuses him anyway.
  await signOut(page);
  await signInAs(page, 2, "dana");
  await page.getByTestId("to-team").click();
  await expect(page.getByTestId("license-team")).toHaveText("Acme Billing");
  await expect(page.getByTestId("license-key")).toHaveCount(0);
  await expect(page.getByTestId("license-banner")).toHaveCount(0);
  const refused = await page.request.post("/api/license", {
    headers: { "X-Shared-Memory-Console": "1" },
    data: { key: KEY },
  });
  expect(refused.status()).toBe(403);
});
