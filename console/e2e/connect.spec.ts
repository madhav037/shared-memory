import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a new member finds Connect your agent at the foot of the contents", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await page.locator(".contents-column.docked").getByTestId("contents-connect").click();

  await expect(page).toHaveURL(/\/connect$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Connect your agent");
});

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
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("[mcp_servers.shared-memory]");
  expect(copied).toContain("[[hooks.SessionStart]]");

  await page.getByTestId("connect-Cline").click();

  await expect(page.getByTestId("agent-files")).toContainText("Once, on each member’s machine");
});

test("a member sees which of their agent's locks a hook takes, and where the agent is asked to take them", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("member-menu").click();
  await page.getByTestId("to-connect").click();

  await page.getByTestId("connect-Codex").click();

  const codex = page.getByTestId("automatic-Codex");
  await expect(codex).toContainText("Every session starts with the briefing");
  await expect(codex).toContainText("A before-edit hook takes each file’s lock");
  await expect(codex).toContainText("A session-end hook ends the session");

  await page.getByTestId("connect-GitHub Copilot").click();

  await expect(page.getByTestId("automatic-Copilot CLI")).toContainText("A before-edit hook takes each file’s lock");
  const vsCode = page.getByTestId("automatic-Copilot in VS Code");
  await expect(vsCode).toContainText("Guidance only: the agent is asked to call take_lock itself");
  await expect(vsCode).toContainText("the session’s locks go when it goes idle");
  await expect(page.getByTestId("agent-automatic")).toContainText("may also run the Copilot CLI hook file");
  await expect(page.getByTestId("agent-automatic")).not.toContainText("no hooks at all");
});
