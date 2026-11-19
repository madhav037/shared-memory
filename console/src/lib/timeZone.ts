/** The picker's value for "Detect automatically": no IANA time zone has this name. */
export const DETECT = "detect";

/** The time zone this browser is set to, as an IANA name, or null when it doesn't say. */
export function browserTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** A time zone as the picker shows it: its IANA name, with spaces for underscores ("America/New York"). */
export function zoneLabel(zone: string): string {
  return zone.replaceAll("_", " ");
}

/**
 * The time zone picker's choices: first "Detect automatically", naming the zone detection gives now, then every zone
 * the server knows.
 */
export function zoneChoices(detectedNow: string | null, zones: string[]): { value: string; label: string }[] {
  const now = detectedNow ? zoneLabel(detectedNow) : "not known yet";
  return [
    { value: DETECT, label: `Detect automatically (now: ${now})` },
    ...zones.map((zone) => ({ value: zone, label: zoneLabel(zone) })),
  ];
}
