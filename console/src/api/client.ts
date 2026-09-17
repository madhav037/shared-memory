import type { components } from "./schema";

export type Status = components["schemas"]["Status"];
export type SignedInMember = components["schemas"]["SignedInMember"];
export type AuditPage = components["schemas"]["AuditPage"];
export type AuditEvent = components["schemas"]["AuditEvent"];
export type Projects = components["schemas"]["Projects"];
export type ProjectSummary = components["schemas"]["ProjectSummary"];
export type Tree = components["schemas"]["Tree"];
export type MemoryDetail = components["schemas"]["MemoryDetail"];
export type SearchResults = components["schemas"]["SearchResults"];
export type SearchHit = components["schemas"]["SearchHit"];
export type IssuedToken = components["schemas"]["IssuedToken"];
export type MemoryHistory = components["schemas"]["MemoryHistory"];
export type MemoryVersion = components["schemas"]["MemoryVersion"];
export type MemoryAtVersion = components["schemas"]["MemoryAtVersion"];
export type MemoryDifference = components["schemas"]["MemoryDifference"];
export type Members = components["schemas"]["Members"];
export type MemberSummary = components["schemas"]["MemberSummary"];

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

function withQuery(path: string, asked: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(asked)) if (value !== undefined && value !== "") query.set(name, String(value));
  const written = query.toString();
  return written ? `${path}?${written}` : path;
}

async function ask<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, headers: { Accept: "application/json", ...options.headers } });
  if (!response.ok) {
    const said = (await response.json().catch(() => null)) as { message?: string } | null;
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
  return ask<AuditPage>(withQuery("/api/audit", filters), { signal });
}

/** The projects this member can reach. */
export function fetchProjects(signal?: AbortSignal): Promise<Projects> {
  return ask<Projects>("/api/projects", { signal });
}

/** A project's memory, folder by folder. */
export function fetchTree(projectId: string, level?: string, signal?: AbortSignal): Promise<Tree> {
  return ask<Tree>(withQuery(`/api/projects/${encodeURIComponent(projectId)}/tree`, { level }), { signal });
}

/** One memory in full. */
export function fetchMemory(projectId: string, path: string, signal?: AbortSignal): Promise<MemoryDetail> {
  return ask<MemoryDetail>(withQuery(`/api/projects/${encodeURIComponent(projectId)}/memory`, { path }), { signal });
}

export type SearchAsked = { query: string; level?: string; type?: string };

/** Memories that match, by meaning and by exact words. */
export function search(projectId: string, asked: SearchAsked, signal?: AbortSignal): Promise<SearchResults> {
  return ask<SearchResults>(withQuery(`/api/projects/${encodeURIComponent(projectId)}/search`, asked), { signal });
}

/** Every version of one memory, newest first. */
export function fetchHistory(projectId: string, path: string, signal?: AbortSignal): Promise<MemoryHistory> {
  return ask<MemoryHistory>(withQuery(`/api/projects/${encodeURIComponent(projectId)}/memory/history`, { path }), {
    signal,
  });
}

/** A memory as it was at one version. */
export function fetchVersion(
  projectId: string,
  path: string,
  commit: string,
  signal?: AbortSignal,
): Promise<MemoryAtVersion> {
  return ask<MemoryAtVersion>(
    withQuery(`/api/projects/${encodeURIComponent(projectId)}/memory/version`, { path, commit }),
    { signal },
  );
}

/** What changed in a memory between two versions. */
export function fetchDifference(
  projectId: string,
  path: string,
  before: string,
  after: string,
  signal?: AbortSignal,
): Promise<MemoryDifference> {
  return ask<MemoryDifference>(
    withQuery(`/api/projects/${encodeURIComponent(projectId)}/memory/difference`, { path, before, after }),
    { signal },
  );
}

/** Issue a new personal token for the signed-in member; the one they had stops working. */
export function reissueMyToken(): Promise<IssuedToken> {
  return ask<IssuedToken>("/api/my-token", { method: "POST", headers: fromConsole });
}

function change<T>(path: string, body?: unknown): Promise<T> {
  return ask<T>(path, {
    method: "POST",
    headers: { ...fromConsole, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** Everyone in the team, with their role and GitHub account. */
export function fetchMembers(signal?: AbortSignal): Promise<Members> {
  return ask<Members>("/api/members", { signal });
}

/** Add a member; their personal token comes back once. */
export function addMember(asked: { employee_id: string; name: string; github?: string }): Promise<IssuedToken> {
  return change<IssuedToken>("/api/members", asked);
}

export function removeMember(employeeId: string): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(employeeId)}/remove`);
}

export function changeMember(employeeId: string, asked: { name?: string; github?: string }): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(employeeId)}/change`, asked);
}

export function setAdmin(employeeId: string, admin: boolean): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(employeeId)}/admin`, { admin });
}

export function handOverOwnership(employeeId: string): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(employeeId)}/ownership`);
}

export const signInUrl = "/api/sign-in/github";
export { ApiError };
