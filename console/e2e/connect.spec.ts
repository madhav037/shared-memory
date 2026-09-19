import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a member picks their coding agent and gets its steps and the repository's files for it", async ({ page }) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await signInAs(page, 1, "olive");
  await page.getByTestId("member-menu").click();
  await page.getByTestId("to-connect").click();

  await page.getByTestId("connect-Codex").click();

  await expect(page.getByTestId("agent-steps")).toContainText(".codex/config.toml");
  await expect(page.getByTestId("agent-steps")).toContainText("Codex 0.78 or later");
  const files = page.getByTestId("agent-files");
  await expect(files.getByTestId("agent-Codex")).toBeVisible();
  await expect(files).toContainText("bearer_token_env_var");
  await expect(files).toContainText("billing-api");
  await expect(files).not.toContainText("smt_");
  await files.getByTestId("copy-.codex/config.toml").click();
  await expect(files.getByTestId("copy-.codex/config.toml")).toContainText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("[mcp_servers.shared-memory]");

  await page.getByTestId("connect-Cline").click();

  await expect(page.getByTestId("agent-files")).toContainText("Once, on each member's machine");
});
