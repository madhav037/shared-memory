import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

// The browser's own time zone, which the console reports after sign-in as the detected one.
test.use({ timezoneId: "Europe/Berlin" });

test("a member sees their detected time zone in Your settings, picks another, and it is kept", async ({ page }) => {
  await signInAs(page, 80, "kai");
  await page.getByTestId("member-menu").click();
  await page.getByTestId("to-settings").click();

  await expect(page.getByRole("heading", { name: "Your settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your time zone" })).toBeVisible();
  const picker = page.getByTestId("time-zone");
  await expect(picker).toHaveValue("Detect automatically (now: Europe/Berlin)");
  await expect(page.getByTestId("time-zone-used")).toHaveText("Your times are shown in Europe/Berlin.");

  await picker.click();
  await picker.fill("Kolkata");
  await page.getByRole("option", { name: "Asia/Kolkata", exact: true }).click();
  await expect(page.getByTestId("time-zone-used")).toHaveText("Your times are shown in Asia/Kolkata.");

  await page.reload();

  await expect(page.getByTestId("time-zone")).toHaveValue("Asia/Kolkata");
  await expect(page.getByTestId("time-zone-used")).toHaveText("Your times are shown in Asia/Kolkata.");

  // Back to detecting, which the other journeys' members never leave.
  await page.getByTestId("time-zone").click();
  await page.getByRole("option", { name: "Detect automatically (now: Europe/Berlin)" }).click();
  await expect(page.getByTestId("time-zone-used")).toHaveText("Your times are shown in Europe/Berlin.");
});
