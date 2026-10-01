import type { components } from "./schema";

export type Status = components["schemas"]["Status"];
export type SignedInMember = components["schemas"]["SignedInMember"];
export type AuditPage = components["schemas"]["AuditPage"];
export type AuditEvent = components["schemas"]["AuditEvent"];
export type Projects = components["schemas"]["Projects"];
export type ProjectSummary = components["schemas"]["ProjectSummary"];
export type ProjectDetail = components["schemas"]["ProjectDetail"];
export type ConnectionFile = components["schemas"]["ConnectionFile"];
export type MemoryDetail = components["schemas"]["MemoryDetail"];
export type SearchResults = components["schemas"]["SearchResults"];
export type SearchHit = components["schemas"]["SearchHit"];
export type IssuedToken = components["schemas"]["IssuedToken"];
export type MemoryHistory = components["schemas"]["MemoryHistory"];
export type MemoryVersion = components["schemas"]["MemoryVersion"];
export type MemoryAtVersion = components["schemas"]["MemoryAtVersion"];
export type Members = components["schemas"]["Members"];
export type Folder = components["schemas"]["Folder"];
export type FileEntry = components["schemas"]["FileEntry"];
export type PinState = components["schemas"]["PinState"];
export type Pins = components["schemas"]["Pins"];
export type Pin = components["schemas"]["Pin"];
export type ChallengeList = components["schemas"]["ChallengeList"];
export type ChallengeDetail = components["schemas"]["ChallengeDetail"];
export type RaisedChallenge = components["schemas"]["RaisedChallenge"];
export type Retired = components["schemas"]["Retired"];
export type MemberSummary = components["schemas"]["MemberSummary"];
export type ProjectBoard = components["schemas"]["ProjectBoard"];
export type BoardArchive = components["schemas"]["BoardArchive"];
export type BoardColumn = components["schemas"]["BoardColumn"];
export type Card = components["schemas"]["Card"];
export type CardDetail = components["schemas"]["CardDetail"];
// What the console sends about a card. The server fills in whatever is left out, so only what must be said is required.
type Asked<T, Required extends keyof T> = Pick<T, Required> & Partial<T>;
export type NewCard = Asked<components["schemas"]["NewCard"], "title">;
export type CardFields = Partial<components["schemas"]["CardFields"]>;
export type CardMove = Asked<components["schemas"]["CardMove"], "column">;
export type MovedCard = components["schemas"]["MovedCard"];
export type DeletedCard = components["schemas"]["DeletedCard"];

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

export type AuditFilters = {
  member?: string;
  kind?: string;
  project?: string;
  since?: string;
  until?: string;
  before?: number;
};

/** A page of the audit log, newest first. */
export function fetchAudit(filters: AuditFilters, signal?: AbortSignal): Promise<AuditPage> {
  return ask<AuditPage>(withQuery("/api/audit", filters), { signal });
}

/** The projects this member can reach. */
export function fetchProjects(signal?: AbortSignal): Promise<Projects> {
  return ask<Projects>("/api/projects", { signal });
}

/** One project: who leads it, and the repositories that belong to it. */
export function fetchProject(projectId: string, signal?: AbortSignal): Promise<ProjectDetail> {
  return ask<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`, { signal });
}

export type SearchAsked = { query: string; level?: string; type?: string; limit?: number };

/** One folder of the team's memory: its folders, with what they hold, and its memories. "" is the top. */
export function fetchFolder(folder: string, signal?: AbortSignal, deep = false): Promise<Folder> {
  return ask<Folder>(withQuery("/api/files", { folder, deep: deep ? "1" : undefined }), { signal });
}

/** Any memory this member can reach, by its path, with its file exactly as Claude reads it. */
export function fetchMemoryAt(path: string, signal?: AbortSignal): Promise<MemoryDetail> {
  return ask<MemoryDetail>(withQuery("/api/memory", { path }), { signal });
}

export function fetchHistoryAt(path: string, signal?: AbortSignal): Promise<MemoryHistory> {
  return ask<MemoryHistory>(withQuery("/api/memory/history", { path }), { signal });
}

export function fetchVersionAt(path: string, commit: string, signal?: AbortSignal): Promise<MemoryAtVersion> {
  return ask<MemoryAtVersion>(withQuery("/api/memory/version", { path, commit }), { signal });
}

/** Pin a project or team memory, or a topic folder, by its path. */
export function pinAt(path: string): Promise<PinState> {
  return change<PinState>("/api/memory/pin", { path });
}

export function unpinAt(path: string): Promise<PinState> {
  return change<PinState>("/api/memory/unpin", { path });
}

/** Retire a memory by its path; another author's raises a challenge they decide. */
export function retireAt(path: string): Promise<Retired> {
  return change<Retired>("/api/memory/retire", { path });
}

/** Memories that match, across team memory and every project this member can reach. */
export function searchEverywhere(asked: SearchAsked, signal?: AbortSignal): Promise<SearchResults> {
  return ask<SearchResults>(withQuery("/api/search", asked), { signal });
}

/** Issue a new personal token for a member of the team; theirs stops working. */
export function reissueToken(memberId: string): Promise<IssuedToken> {
  return change<IssuedToken>(`/api/members/${encodeURIComponent(memberId)}/token`);
}

/** Everything pinned that this project's sessions are briefed with. */
export function fetchPins(projectId: string, signal?: AbortSignal): Promise<Pins> {
  return ask<Pins>(`/api/projects/${encodeURIComponent(projectId)}/pins`, { signal });
}

/** Challenges waiting for this member's decision, and the ones they raised. */
export function fetchChallenges(signal?: AbortSignal): Promise<ChallengeList> {
  return ask<ChallengeList>("/api/challenges", { signal });
}

/** Accept a challenge or reject it. */
export function decideChallenge(challengeId: number, decision: "accept" | "reject"): Promise<ChallengeList> {
  return change<ChallengeList>(`/api/challenges/${challengeId}/decide`, { decision });
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
export function addMember(asked: { member_id: string; name: string; github?: string }): Promise<IssuedToken> {
  return change<IssuedToken>("/api/members", asked);
}

export function removeMember(memberId: string): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(memberId)}/remove`);
}

export function changeMember(memberId: string, asked: { name?: string; github?: string }): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(memberId)}/change`, asked);
}

export function setAdmin(memberId: string, admin: boolean): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(memberId)}/admin`, { admin });
}

export function handOverOwnership(memberId: string): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(memberId)}/ownership`);
}

/** Create a project; whoever creates it is its first project lead. */
export function createProject(name: string): Promise<ProjectDetail> {
  return change<ProjectDetail>("/api/projects", { name });
}

export function renameProject(projectId: string, name: string): Promise<ProjectDetail> {
  return change<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}/rename`, { name });
}

export function appointLead(projectId: string, memberId: string): Promise<ProjectDetail> {
  return change<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}/leads`, { member_id: memberId });
}

export function removeLead(projectId: string, memberId: string): Promise<ProjectDetail> {
  const where = `${encodeURIComponent(projectId)}/leads/${encodeURIComponent(memberId)}`;
  return change<ProjectDetail>(`/api/projects/${where}/remove`);
}

/** Close a project to its access list, or open it to the whole team again. */
export function restrictProject(projectId: string, restricted: boolean): Promise<ProjectDetail> {
  return change<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}/restrict`, { restricted });
}

export function grantAccess(projectId: string, memberId: string): Promise<ProjectDetail> {
  return change<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}/access`, { member_id: memberId });
}

export function revokeAccess(projectId: string, memberId: string): Promise<ProjectDetail> {
  const where = `${encodeURIComponent(projectId)}/access/${encodeURIComponent(memberId)}`;
  return change<ProjectDetail>(`/api/projects/${where}/remove`);
}

export function addRepository(projectId: string, name: string): Promise<ProjectDetail> {
  return change<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}/repositories`, { name });
}

export function removeRepository(projectId: string, name: string): Promise<ProjectDetail> {
  const where = `${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(name)}`;
  return change<ProjectDetail>(`/api/projects/${where}/remove`);
}

export const signInUrl = "/api/sign-in/github";

/** What a board is narrowed to: an assignee by member ID, a label and a priority. */
export type BoardFilters = { assignee?: string; label?: string; priority?: string };

/** A project's board, column by column, top first. */
export function fetchBoard(projectId: string, filters: BoardFilters, signal?: AbortSignal): Promise<ProjectBoard> {
  return ask<ProjectBoard>(withQuery(`/api/projects/${encodeURIComponent(projectId)}/board`, filters), { signal });
}

/** The cards that have left a project's board, the most recently done first. */
export function fetchArchive(projectId: string, filters: BoardFilters, signal?: AbortSignal): Promise<BoardArchive> {
  return ask<BoardArchive>(withQuery(`/api/projects/${encodeURIComponent(projectId)}/board/archive`, filters), {
    signal,
  });
}

/** One card whole, with its links and comments. */
export function fetchCard(projectId: string, number: number, signal?: AbortSignal): Promise<CardDetail> {
  return ask<CardDetail>(`/api/projects/${encodeURIComponent(projectId)}/cards/${number}`, { signal });
}

function cardPath(projectId: string, number?: number, what = ""): string {
  const card = number === undefined ? "" : `/${number}${what ? `/${what}` : ""}`;
  return `/api/projects/${encodeURIComponent(projectId)}/cards${card}`;
}

/** Add a card to the bottom of To do. */
export function addCard(projectId: string, card: NewCard): Promise<CardDetail> {
  return change<CardDetail>(cardPath(projectId), card);
}

/** Change a card's fields: only those given change. */
export function editCard(projectId: string, number: number, fields: CardFields): Promise<CardDetail> {
  return change<CardDetail>(cardPath(projectId, number), fields);
}

/**
 * Move a card to a column, at a position in it (1 is the top); Blocked takes a reason. A card entering Done says what
 * became of the known issues it fixes.
 */
export function moveCard(projectId: string, number: number, move: CardMove): Promise<MovedCard> {
  return change<MovedCard>(cardPath(projectId, number, "move"), move);
}

/** Claim a card in To do: the member becomes its assignee and it moves to Doing. */
export function claimCard(projectId: string, number: number): Promise<CardDetail> {
  return change<CardDetail>(cardPath(projectId, number, "claim"));
}

export function commentCard(projectId: string, number: number, text: string): Promise<CardDetail> {
  return change<CardDetail>(cardPath(projectId, number, "comment"), { text });
}

export function deleteCard(projectId: string, number: number): Promise<DeletedCard> {
  return change<DeletedCard>(cardPath(projectId, number, "delete"));
}
