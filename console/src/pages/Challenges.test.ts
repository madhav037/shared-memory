import { MantineProvider } from "@mantine/core";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { ChallengeDetail } from "../api/client";
import { Proposal } from "./Challenges";

const TARGET: ChallengeDetail["target"] = {
  path: "company/conventions/invoice-numbers.md",
  title: "Invoice numbers",
  summary: "Invoices number by year.",
  body: "Invoices are numbered by year.",
  level: "company",
  type: "convention",
  author: "emp-2",
  status: "active",
  tied_files: [],
  source: "---\ntitle: Invoice numbers\n---\nInvoices are numbered by year.\n",
};

/** A supersede raised from memory the member can't reach, as the server sends it: nothing of that memory. */
const UNSEEN: ChallengeDetail = {
  challenge_id: 12,
  kind: "supersede",
  project_id: null,
  raised_by: "emp-1",
  raised_at: "2026-11-20T09:00:00Z",
  yours: true,
  decides_as: "author",
  foundation: null,
  foundation_name: null,
  target: TARGET,
  challenger: null,
  challenger_unseen: true,
  reasoning: null,
  reason: null,
  evidence: [],
  count: null,
};

const proposed = (challenge: ChallengeDetail) =>
  renderToString(
    createElement(
      MantineProvider,
      null,
      createElement(
        MemoryRouter,
        null,
        createElement(Proposal, {
          challenge,
          who: (memberId: string) => memberId,
          view: "source",
          marked: true,
          deciding: null,
          refused: null,
          onDecide: () => undefined,
        }),
      ),
    ),
  );

describe("a challenge raised from memory the member can't reach", () => {
  it("is shown by its number alone, in place of the memory offered", () => {
    const shown = proposed(UNSEEN);

    expect(shown).toContain('data-testid="challenger-unseen"');
    expect(shown).toContain("Raised from memory you can&#x27;t reach, so only its number is shown.");
    expect(shown).toContain("Challenge <!-- -->12");
    expect(shown).not.toContain("Nothing in its place");
  });

  it("is still decided as the supersede it is", () => {
    const shown = proposed(UNSEEN);

    expect(shown).toContain("Accept: supersede it");
    expect(shown).toContain("Reject: keep it as it is");
    expect(shown).not.toContain("Accept: retire it");
  });

  it("isn't how a retire, which offers nothing, is shown", () => {
    const shown = proposed({ ...UNSEEN, kind: "retire", challenger_unseen: false });

    expect(shown).not.toContain('data-testid="challenger-unseen"');
    expect(shown).toContain("Accept: retire it");
  });
});
