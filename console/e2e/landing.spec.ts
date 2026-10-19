import { expect, test } from "@playwright/test";

test("before signing in, the landing page prices team plans hosted by us or self-hosted", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("every agent knows");

  const pricing = page.locator("#pricing");
  const price = (size: number) => page.getByTestId(`plan-${size}`).locator(".lp-price");
  await expect(price(5)).toHaveAttribute("aria-label", "$468 a year");
  await expect(page.getByTestId("plan-5")).toContainText("can’t be cancelled partway through");

  await pricing.getByRole("radio", { name: "Monthly" }).click();
  await expect(price(5)).toHaveAttribute("aria-label", "$49 a month");
  await expect(page.getByTestId("plan-5")).toContainText("Cancel any time.");
  await expect(page.getByTestId("plan-10")).toContainText("Start a 7-day trial");

  await pricing.getByRole("radio", { name: "Self-hosted" }).click();
  await expect(price(15)).toHaveAttribute("aria-label", "$948 a year");
  await expect(page.getByTestId("plan-15")).toContainText("Get a license");
  await expect(pricing.getByRole("radiogroup", { name: "Billing" })).toHaveCount(0);
});

test("a visitor decides the example challenge and reads a memory as it stood", async ({ page }) => {
  await page.goto("/");

  const challenge = page.getByTestId("landing-challenge");
  await challenge.getByRole("button", { name: "Accept and supersede" }).click();
  await expect(challenge).toContainText("Superseded.");
  await challenge.getByRole("button", { name: "Decide again" }).click();
  await challenge.getByRole("button", { name: "Keep mine" }).click();
  await expect(challenge).toContainText("Kept.");

  const history = page.getByTestId("landing-history");
  await history.getByRole("button", { name: "v1 · March" }).click();
  await expect(history).toContainText("As it stood on 3 March 2026");
  await history.getByRole("button", { name: "v3 · September" }).click();
  await expect(history).toContainText("In force.");
});

test("the landing page's address tells search engines and link previews what Shared Memory is before any script runs", async ({
  request,
}) => {
  const html = await (await request.get("/")).text();

  expect(html).toContain("<title>Shared Memory: Team Memory for Claude Code, Cursor &amp; Codex</title>");
  expect(html).toMatch(/<meta\s+name="description"\s+content="One memory every coding agent on your team reads and writes\./);
  expect(html).toMatch(/<meta\s+property="og:title"\s+content="What one agent learns, every agent knows\."/);
  expect(html).toMatch(/<meta\s+name="twitter:card"\s+content="summary"/);

  const described = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
  const graph = JSON.parse(described![1]!)["@graph"] as { "@type": string; name: string }[];
  expect(graph.map((thing) => thing["@type"])).toEqual(["Organization", "SoftwareApplication"]);
});

test("a section's heading wipes into view once the visitor scrolls to it", async ({ page }) => {
  await page.goto("/");

  const heading = page.locator("#how h2");
  await heading.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await expect(heading).toHaveClass(/\bin\b/);
});
