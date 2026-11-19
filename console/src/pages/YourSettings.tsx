import { Select } from "@mantine/core";
import { useState } from "react";

import { chooseMyTimeZone, fetchMyTimeZone, reportMyTimeZone, type YourTimeZoneChoices } from "../api/client";
import { Placeholder, Refusal } from "../components/Bits";
import { browserTimeZone, DETECT, zoneChoices, zoneLabel } from "../lib/timeZone";
import { useAsked } from "../lib/useAsked";

/** The signed-in member's own settings. A member setting, not a memory write (ADR-0009). */
export function YourSettings() {
  return (
    <div className="narrow">
      <h1 className="page-title">Your settings</h1>
      <YourTimeZone />
    </div>
  );
}

/** The member's time zone, with this browser's zone kept as the detected one first if nothing is chosen and the
 * console's report after sign-in hasn't reached the server yet. */
async function withThisBrowser(signal: AbortSignal): Promise<YourTimeZoneChoices> {
  const asked = await fetchMyTimeZone(signal);
  const browser = browserTimeZone();
  const reported = asked.chosen === null && browser && asked.detected !== browser && asked.time_zones.includes(browser);
  return reported ? { ...asked, ...(await reportMyTimeZone(browser)) } : asked;
}

function YourTimeZone() {
  const { answer, refused, setAnswer } = useAsked(withThisBrowser, []);
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // What detecting gives now: this browser's zone, which the console reports after sign-in, else the last detected.
  const detectedNow = browserTimeZone() ?? answer?.detected ?? null;

  async function choose(value: string | null) {
    if (!answer || value === null) return;
    setSaving(true);
    setProblem(null);
    try {
      let kept = await chooseMyTimeZone(value === DETECT ? null : value);
      const browser = browserTimeZone();
      if (value === DETECT && browser && answer.time_zones.includes(browser)) kept = await reportMyTimeZone(browser);
      setAnswer({ ...answer, ...kept });
    } catch (refusal) {
      setProblem((refusal as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const shownIn = answer?.chosen ?? answer?.detected ?? null;
  return (
    <section aria-labelledby="time-zone-heading">
      <h2 className="section-heading" id="time-zone-heading">
        Your time zone
      </h2>
      <p className="section-lede">
        The times in the warnings your coding agent shows you are given in this time zone. Detected automatically, it
        follows the browser you sign in with.
      </p>
      {refused && <Refusal testid="time-zone-refused">{refused}</Refusal>}
      {problem && <Refusal testid="time-zone-problem">{problem}</Refusal>}
      {!answer ? (
        !refused && <Placeholder lines={2} />
      ) : (
        <>
          <Select
            aria-labelledby="time-zone-heading"
            data={zoneChoices(detectedNow, answer.time_zones)}
            value={answer.chosen ?? DETECT}
            onChange={(value) => void choose(value)}
            searchable
            allowDeselect={false}
            nothingFoundMessage="No time zone by that name"
            disabled={saving}
            maxDropdownHeight={320}
            data-testid="time-zone"
          />
          <p className="section-lede" data-testid="time-zone-used">
            {shownIn
              ? `Your times are shown in ${zoneLabel(shownIn)}.`
              : "Your times are shown as time left, until a time zone is detected."}
          </p>
        </>
      )}
    </section>
  );
}
