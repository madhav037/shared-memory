import { describe, expect, it } from "vitest";

import { money, PLAN_SIZES, planPrice } from "./plans";

describe("planPrice", () => {
  it("bills a hosted server monthly with no commitment", () => {
    expect(planPrice("hosted", "monthly", 5)).toEqual({
      amount: 49,
      per: "a month",
      terms: "Billed monthly. Cancel any time.",
      action: "Start a 7-day trial",
    });
  });

  it("bills a hosted server yearly up front, says what it saves, and can't be cancelled", () => {
    const price = planPrice("hosted", "yearly", 10);
    expect(price.amount).toBe(828);
    expect(price.per).toBe("a year");
    expect(price.terms).toContain("$240 less than monthly");
    expect(price.terms).toContain("can’t be cancelled");
  });

  it("licenses a self-hosted server yearly whatever billing was chosen", () => {
    expect(planPrice("self-hosted", "monthly", 15)).toEqual(planPrice("self-hosted", "yearly", 15));
    expect(planPrice("self-hosted", "monthly", 15)).toMatchObject({ amount: 948, per: "a year", action: "Get a license" });
  });

  it("saves at least a fifth by paying yearly, and a license costs less than a hosted server", () => {
    for (const size of PLAN_SIZES) {
      const monthly = planPrice("hosted", "monthly", size).amount * 12;
      const yearly = planPrice("hosted", "yearly", size).amount;
      expect(yearly).toBeLessThanOrEqual(monthly * 0.8);
      expect(planPrice("self-hosted", "yearly", size).amount).toBeLessThan(yearly);
    }
  });

  it("writes amounts in dollars with thousands separated", () => {
    expect(money(1188)).toBe("$1,188");
  });
});
