import { describe, expect, it } from "vitest";

import { DETECT, zoneChoices, zoneLabel } from "./timeZone";

describe("the time zone picker's choices", () => {
  it("offers detecting automatically first, naming the zone it detects now", () => {
    const [first] = zoneChoices("Europe/Berlin", ["Asia/Kolkata", "Europe/Berlin"]);

    expect(first).toEqual({ value: DETECT, label: "Detect automatically (now: Europe/Berlin)" });
  });

  it("then every zone the server knows, in its order, by name", () => {
    const choices = zoneChoices("Europe/Berlin", ["America/New_York", "Asia/Kolkata"]);

    expect(choices.slice(1)).toEqual([
      { value: "America/New_York", label: "America/New York" },
      { value: "Asia/Kolkata", label: "Asia/Kolkata" },
    ]);
  });

  it("says when no zone is detected yet", () => {
    expect(zoneChoices(null, [])[0]?.label).toBe("Detect automatically (now: not known yet)");
  });

  it("shows a zone with spaces for underscores", () => {
    expect(zoneLabel("America/Argentina/Buenos_Aires")).toBe("America/Argentina/Buenos Aires");
  });
});
