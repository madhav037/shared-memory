/** What a team pays for Shared Memory: a plan's size, who runs its server, and how it is billed. Draft prices. */

export type Hosting = "hosted" | "self-hosted";
export type Billing = "monthly" | "yearly";
export type PlanSize = 5 | 10 | 15;

export const PLAN_SIZES: PlanSize[] = [5, 10, 15];
export const TRIAL_DAYS = 7;

/** In dollars: a hosted server billed monthly or yearly, and a license, which is only ever yearly. */
const PRICES = {
  hosted: { monthly: { 5: 49, 10: 89, 15: 129 }, yearly: { 5: 468, 10: 828, 15: 1188 } },
  "self-hosted": { yearly: { 5: 348, 10: 708, 15: 948 } },
} as const;

export interface PlanPrice {
  amount: number;
  per: "a month" | "a year";
  /** The billing's terms in a sentence or two: when it is paid, and whether it can be cancelled. */
  terms: string;
  action: string;
}

export function money(amount: number): string {
  return "$" + amount.toLocaleString("en-US");
}

/** A self-hosted server is licensed for a year, so it is priced yearly whatever billing is chosen. */
export function planPrice(hosting: Hosting, billing: Billing, size: PlanSize): PlanPrice {
  if (hosting === "self-hosted") {
    return {
      amount: PRICES["self-hosted"].yearly[size],
      per: "a year",
      terms: "A 12-month license, paid up front, with every update while it runs. It can’t be cancelled partway through.",
      action: "Get a license",
    };
  }
  const action = `Start a ${TRIAL_DAYS}-day trial`;
  if (billing === "monthly") {
    return { amount: PRICES.hosted.monthly[size], per: "a month", terms: "Billed monthly. Cancel any time.", action };
  }
  const amount = PRICES.hosted.yearly[size];
  const saved = PRICES.hosted.monthly[size] * 12 - amount;
  return {
    amount,
    per: "a year",
    terms: `Paid once a year, up front: ${money(saved)} less than monthly. It can’t be cancelled partway through.`,
    action,
  };
}
