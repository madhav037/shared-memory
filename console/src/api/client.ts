import type { components } from "./schema";

export type Status = components["schemas"]["Status"];

/** Ask the server what it knows about this console: whether it answers, and who is signed in. */
export async function fetchStatus(signal?: AbortSignal): Promise<Status> {
  const response = await fetch("/api/status", { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`The server answered ${response.status}.`);
  return (await response.json()) as Status;
}
