import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

// Kai keeps Treasury's Product foundation, and Nell has asked for her settlements memory to join it.
test("a keeper accepts a foundation challenge from its own section and the memory joins the foundation", async ({
  page,
}) => {
  await signInAs(page, 80, "kai");
  await page.getByTestId("to-challenges").click();

  await expect(page.getByRole("heading", { name: "Foundation challenges" })).toBeVisible();
  const section = page.getByTestId("foundation-challenges");
  await expect(section.getByTestId("foundation-mark")).toHaveText("Product foundation");
  await expect(section).toContainText("Settlements close at 17:00 UTC");
  await expect(section).toContainText("Nell Raiser wants to add it to the Product foundation");
  await expect(section).toContainText("yours to decide as a keeper of the foundation");
  await expect(section.getByTestId("reasoning-text")).toHaveText(
    "Settlement timing is a product rule that finance and support both rely on.",
  );
  // Nothing here is a challenge to a single memory.
  await expect(page.getByTestId("waiting")).toHaveCount(0);

  await section.getByRole("button", { name: "Accept: add it to the foundation" }).click();

  const slip = page.getByTestId("decided");
  await expect(slip).toContainText("You accepted it. ‘Settlements close at 17:00 UTC’ is now in the Product foundation.");
  await expect(page.getByTestId("foundation-challenges")).toHaveCount(0);

  // The memory is now where the foundation keeps it.
  await slip.getByRole("link", { name: "Read it" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Settlements close at 17:00 UTC");
  expect(decodeURIComponent(new URL(page.url()).searchParams.get("path") ?? "")).toContain("/foundations/product/");
});
