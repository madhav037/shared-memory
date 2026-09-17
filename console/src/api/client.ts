import type { components } from "./schema";

export type Status = components["schemas"]["Status"];
export type SignedInMember = components["schemas"]["SignedInMember"];
export type AuditPage = components["schemas"]["AuditPage"];
export type AuditEvent = components["schemas"]["AuditEvent"];

/** The header that tells the server a request came from the console, not from another site. */
const fromConsole = { "X-Shared-Memory-Console": "1" };

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function ask<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, headers: { Accept: "application/json", ...options.headers } });
  if (!response.ok) {
    const said = await response.json().catch(() => null);
    throw new ApiError(said?.message ?? `The server answered ${response.status}.`, response.status);
  }
  return (await response.json()) as T;
}

/** Ask the server whether it answers, and who is signed in. */
export function fetchStatus(signal?: AbortSignal): Promise<Status> {
  return ask<Status>("/api/status", { signal });
}

/** End this console session. */
export function signOut(): Promise<Status> {
  return ask<Status>("/api/sign-out", { method: "POST", headers: fromConsole });
}

export type AuditFilters = { member?: string; kind?: string; since?: string; until?: string; before?: number };

/** A page of the audit log, newest first. */
export function fetchAudit(filters: AuditFilters, signal?: AbortSignal): Promise<AuditPage> {
  const asked = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) if (value) asked.set(name, String(value));
  return ask<AuditPage>(`/api/audit?${asked.toString()}`, { signal });
}

export const signInUrl = "/api/sign-in/github";
export { ApiError };
