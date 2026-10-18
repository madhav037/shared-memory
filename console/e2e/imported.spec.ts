import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("a memory imported in its writer's name shows its importer and its source beside its author", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Money is integer cents");

  const details = page.getByTestId("memory-details");
  await expect(details).toContainText("Mira Maker");
  await expect(details.getByTestId("imported-by")).toHaveText("Olive Owner");
  await expect(details.getByTestId("imported-from")).toHaveText("billing-api:CLAUDE.md");
});
