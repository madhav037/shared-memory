import type { components } from "./schema";

export type Status = components["schemas"]["Status"];
export type SignedInMember = components["schemas"]["SignedInMember"];

/** The header that tells the server a request came from the console, not from another site. */
const fromConsole = { "X-Shared-Memory-Console": "1" };

/** Ask the server whether it answers, and who is signed in. */
export async function fetchStatus(signal?: AbortSignal): Promise<Status> {
  const response = await fetch("/api/status", { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`The server answered ${response.status}.`);
  return (await response.json()) as Status;
}

/** End this console session. */
export async function signOut(): Promise<Status> {
  const response = await fetch("/api/sign-out", { method: "POST", headers: { ...fromConsole, Accept: "application/json" } });
  if (!response.ok) throw new Error(`The server answered ${response.status}.`);
  return (await response.json()) as Status;
}

export const signInUrl = "/api/sign-in/github";
