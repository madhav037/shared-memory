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
export type DoubtEvidence = components["schemas"]["DoubtEvidence"];
export type InDoubtMark = components["schemas"]["InDoubtMark"];
export type DecidedChallenges = components["schemas"]["DecidedChallenges"];
export type Decided = components["schemas"]["Decided"];
export type RaisedChallenge = components["schemas"]["RaisedChallenge"];
export type Notices = components["schemas"]["Notices"];
export type Notice = components["schemas"]["Notice"];
export type Retired = components["schemas"]["Retired"];
export type MemberSummary = components["schemas"]["MemberSummary"];
export type ProjectBoard = components["schemas"]["ProjectBoard"];
export type BoardArchive = components["schemas"]["BoardArchive"];
export type BoardColumn = components["schemas"]["BoardColumn"];
export type Card = components["schemas"]["Card"];
export type CardDetail = components["schemas"]["CardDetail"];
export type ProjectSessions = components["schemas"]["ProjectSessions"];
export type ProjectHealth = components["schemas"]["ProjectHealth"];
export type OnboardingProgress = components["schemas"]["OnboardingProgress"];
export type OnboardingEntry = components["schemas"]["OnboardingEntry"];
export type InterviewMemories = components["schemas"]["InterviewMemories"];
export type ActiveSession = components["schemas"]["ActiveSession"];
export type NamedSession = components["schemas"]["NamedSession"];
export type SessionCollision = components["schemas"]["SessionCollision"];
export type SessionGate = components["schemas"]["SessionGate"];
export type SessionMessage = components["schemas"]["SessionMessage"];
export type SessionHandoffNote = components["schemas"]["SessionHandoffNote"];
export type RateLimits = components["schemas"]["RateLimits"];
export type LicenseState = components["schemas"]["LicenseState"];
export type RateLimitChange = components["schemas"]["RateLimitChange"];
export type YourTimeZone = components["schemas"]["YourTimeZone"];
export type YourTimeZoneChoices = components["schemas"]["YourTimeZoneChoices"];
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

const whenLimited = new Set<(message: string) => void>();

/** Hear of every call the server limits (a 429), whichever page made it, with what the server said. Returns how to stop. */
export function onRateLimited(listener: (message: string) => void): () => void {
  whenLimited.add(listener);
  return () => void whenLimited.delete(listener);
}

async function ask<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, headers: { Accept: "application/json", ...options.headers } });
  if (!response.ok) await refuse(response);
  return (await response.json()) as T;
}

/** Throw what the server said when it refused a call. */
async function refuse(response: Response): Promise<never> {
  const said = (await response.json().catch(() => null)) as { message?: string } | null;
  const message = said?.message ?? `The server answered ${response.status}.`;
  if (response.status === 429) whenLimited.forEach((listener) => listener(message));
  throw new ApiError(message, response.status);
}

/**
 * Download all of the company's data as one zip, which the browser saves under the name the server gives it. A POST
 * with the console's header, so no other page, and no image in a member's text, can start one.
 */
export async function downloadExport(): Promise<void> {
  const response = await fetch("/api/export", { method: "POST", headers: fromConsole });
  if (!response.ok) await refuse(response);
  const named = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1];
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob());
  link.download = named ?? "shared-memory-export.zip";
  link.click();
  // Kept a moment, so the browser has started saving it before the address goes.
  setTimeout(() => URL.revokeObjectURL(link.href), 60_000);
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
  /** How many changes a page holds; the server's own number when left out. */
  limit?: number;
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

/** One folder of the company's memory: its folders, with what they hold, and its memories. "" is the top. */
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

/** Pin a project or company memory, or a topic folder, by its path. */
export function pinAt(path: string): Promise<PinState> {
  return change<PinState>("/api/memory/pin", { path });
}

export function unpinAt(path: string): Promise<PinState> {
  return change<PinState>("/api/memory/unpin", { path });
}

/** The memories written from this member's interviews, which they author. */
export function fetchInterviewed(signal?: AbortSignal): Promise<InterviewMemories> {
  return ask<InterviewMemories>("/api/interviewed", { signal });
}

/** Retire a memory by its path; another author's raises a challenge they decide. */
export function retireAt(path: string): Promise<Retired> {
  return change<Retired>("/api/memory/retire", { path });
}

/** Memories that match, across company memory and every project this member can reach. */
export function searchEverywhere(asked: SearchAsked, signal?: AbortSignal): Promise<SearchResults> {
  return ask<SearchResults>(withQuery("/api/search", asked), { signal });
}

/** Issue a new personal token for a member of the company; theirs stops working. */
export function reissueToken(memberId: string): Promise<IssuedToken> {
  return change<IssuedToken>(`/api/members/${encodeURIComponent(memberId)}/token`);
}

/** A project's onboarding progress: every entry for its leads and the company's admins, the member's own otherwise. */
export function fetchOnboarding(projectId: string, signal?: AbortSignal): Promise<OnboardingProgress> {
  return ask<OnboardingProgress>(`/api/projects/${encodeURIComponent(projectId)}/onboarding`, { signal });
}

/** Everything pinned that this project's sessions are briefed with. */
/** A project's health, for its leads and the company's admins: its possibly outdated memory and its memory in doubt. */
export function fetchHealth(projectId: string, signal?: AbortSignal): Promise<ProjectHealth> {
  return ask<ProjectHealth>(`/api/projects/${encodeURIComponent(projectId)}/health`, { signal });
}

export function fetchPins(projectId: string, signal?: AbortSignal): Promise<Pins> {
  return ask<Pins>(`/api/projects/${encodeURIComponent(projectId)}/pins`, { signal });
}

/** Challenges waiting for this member's decision, and the ones they raised. */
export function fetchChallenges(signal?: AbortSignal): Promise<ChallengeList> {
  return ask<ChallengeList>("/api/challenges", { signal });
}

/**
 * What this member has been told, newest first. Only a read: each notice still waits for their next briefing.
 */
export function fetchNotices(signal?: AbortSignal): Promise<Notices> {
  return ask<Notices>("/api/notices", { signal });
}

/** Decide a challenge, or a level contradiction by keeping an exception (with a reason) or following; the answer says
 * what that did, and what is still waiting. */
export function decideChallenge(
  challengeId: number,
  decision: "accept" | "reject" | "keep_exception" | "follow",
  reason?: string,
): Promise<DecidedChallenges> {
  return change<DecidedChallenges>(`/api/challenges/${challengeId}/decide`, { decision, reason: reason ?? null });
}

/** Issue a new personal token for the signed-in member; the one they had stops working. */
export function reissueMyToken(): Promise<IssuedToken> {
  return ask<IssuedToken>("/api/my-token", { method: "POST", headers: fromConsole });
}

/** The signed-in member's time zone, and every time zone they can choose from. */
export function fetchMyTimeZone(signal?: AbortSignal): Promise<YourTimeZoneChoices> {
  return ask<YourTimeZoneChoices>("/api/my-time-zone", { signal });
}

/** Choose the signed-in member's time zone, or null to have it detected from the browser. */
export function chooseMyTimeZone(timeZone: string | null): Promise<YourTimeZone> {
  return change<YourTimeZone>("/api/my-time-zone", { time_zone: timeZone });
}

/** Report the time zone this browser is set to; kept as the detected one while the member has chosen none. */
export function reportMyTimeZone(timeZone: string): Promise<YourTimeZone> {
  return change<YourTimeZone>("/api/my-time-zone/detected", { time_zone: timeZone });
}

function change<T>(path: string, body?: unknown): Promise<T> {
  return ask<T>(path, {
    method: "POST",
    headers: { ...fromConsole, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** The server's rate limit, and whether this member may change it. */
export function fetchRateLimits(signal?: AbortSignal): Promise<RateLimits> {
  return ask<RateLimits>("/api/rate-limits", { signal });
}

/** Change the rate limit, or switch it off. Admins only. */
export function changeRateLimits(asked: RateLimitChange): Promise<RateLimits> {
  return change<RateLimits>("/api/rate-limits", asked);
}

/** The server's license key: its status, company, member cap and expiry. */
export function fetchLicense(signal?: AbortSignal): Promise<LicenseState> {
  return ask<LicenseState>("/api/license", { signal });
}

/** Install a license key. Admins only. */
export function installLicense(key: string): Promise<LicenseState> {
  return change<LicenseState>("/api/license", { key });
}

/** Everyone in the company, with their role and GitHub account. */
export function fetchMembers(signal?: AbortSignal): Promise<Members> {
  return ask<Members>("/api/members", { signal });
}

/** Add a member; their personal token comes back once. */
export function addMember(asked: { member_id: string; name: string; github?: string; email?: string }): Promise<IssuedToken> {
  return change<IssuedToken>("/api/members", asked);
}

export function removeMember(memberId: string): Promise<Members> {
  return change<Members>(`/api/members/${encodeURIComponent(memberId)}/remove`);
}

export function changeMember(memberId: string, asked: { name?: string; github?: string; email?: string }): Promise<Members> {
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

export function addFoundation(projectId: string, name: string): Promise<ProjectDetail> {
  return change<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}/foundations`, { name });
}

export function removeFoundation(projectId: string, foundation: string): Promise<ProjectDetail> {
  const where = `${encodeURIComponent(projectId)}/foundations/${encodeURIComponent(foundation)}`;
  return change<ProjectDetail>(`/api/projects/${where}/remove`);
}

export function assignKeeper(projectId: string, foundation: string, memberId: string): Promise<ProjectDetail> {
  const where = `${encodeURIComponent(projectId)}/foundations/${encodeURIComponent(foundation)}`;
  return change<ProjectDetail>(`/api/projects/${where}/keepers`, { member_id: memberId });
}

export function removeKeeper(projectId: string, foundation: string, memberId: string): Promise<ProjectDetail> {
  const where = `${encodeURIComponent(projectId)}/foundations/${encodeURIComponent(foundation)}/keepers/${encodeURIComponent(memberId)}`;
  return change<ProjectDetail>(`/api/projects/${where}/remove`);
}

/** Close a project to its access list, or open it to the whole company again. */
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

/** A project's active sessions, the oldest first, each with its activity and the files it holds a lock on. */
export function fetchSessions(projectId: string, signal?: AbortSignal): Promise<ProjectSessions> {
  return ask<ProjectSessions>(`/api/projects/${encodeURIComponent(projectId)}/sessions`, { signal });
}

function sessionsPath(projectId: string, rest: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/sessions/${rest}`;
}

/** Send a message, such as a reply, from the signed-in member's session in the project; answers with the page anew. */
export function sendMessage(projectId: string, to: string, text: string): Promise<ProjectSessions> {
  return change<ProjectSessions>(sessionsPath(projectId, "messages"), { to, text });
}

/** Agree to or refuse the gate a member's session has on the signed-in member's session's work. */
export function answerGate(projectId: string, memberId: string, answer: "agree" | "refuse"): Promise<ProjectSessions> {
  return change<ProjectSessions>(sessionsPath(projectId, `gates/${encodeURIComponent(memberId)}/answer`), { answer });
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

export type Departments = components["schemas"]["Departments"];
export type DepartmentSummary = components["schemas"]["DepartmentSummary"];

/** Every department of the company, with its leads and the projects in it this member can reach (ADR-0032). */
export function fetchDepartments(signal?: AbortSignal): Promise<Departments> {
  return ask<Departments>("/api/departments", { signal });
}

export type DepartmentPage = components["schemas"]["DepartmentPage"];
export type MemoryCounts = components["schemas"]["MemoryCounts"];

/** One department's page (#636): its projects and department memory, and for its leads and the admins its roll-up. */
export function fetchDepartment(departmentId: string, signal?: AbortSignal): Promise<DepartmentPage> {
  return ask<DepartmentPage>(`/api/departments/${encodeURIComponent(departmentId)}`, { signal });
}

export function createDepartment(name: string): Promise<Departments> {
  return change<Departments>("/api/departments", { name });
}

export function renameDepartment(departmentId: string, name: string): Promise<Departments> {
  return change<Departments>(`/api/departments/${encodeURIComponent(departmentId)}/rename`, { name });
}

export function removeDepartment(departmentId: string): Promise<Departments> {
  return change<Departments>(`/api/departments/${encodeURIComponent(departmentId)}/remove`);
}

export function appointDepartmentLead(departmentId: string, memberId: string): Promise<Departments> {
  return change<Departments>(`/api/departments/${encodeURIComponent(departmentId)}/leads`, { member_id: memberId });
}

export function removeDepartmentLead(departmentId: string, memberId: string): Promise<Departments> {
  const where = `${encodeURIComponent(departmentId)}/leads/${encodeURIComponent(memberId)}`;
  return change<Departments>(`/api/departments/${where}/remove`);
}

export function moveProjectIn(departmentId: string, projectId: string): Promise<Departments> {
  return change<Departments>(`/api/departments/${encodeURIComponent(departmentId)}/projects`, { project_id: projectId });
}

export function moveProjectOut(departmentId: string, projectId: string): Promise<Departments> {
  const where = `${encodeURIComponent(departmentId)}/projects/${encodeURIComponent(projectId)}`;
  return change<Departments>(`/api/departments/${where}/remove`);
}

/** Close a department to its access list, or open it to the whole company again. */
export function restrictDepartment(departmentId: string, restricted: boolean): Promise<Departments> {
  return change<Departments>(`/api/departments/${encodeURIComponent(departmentId)}/restrict`, { restricted });
}

export function grantDepartmentAccess(departmentId: string, memberId: string): Promise<Departments> {
  return change<Departments>(`/api/departments/${encodeURIComponent(departmentId)}/access`, { member_id: memberId });
}

export function revokeDepartmentAccess(departmentId: string, memberId: string): Promise<Departments> {
  const where = `${encodeURIComponent(departmentId)}/access/${encodeURIComponent(memberId)}`;
  return change<Departments>(`/api/departments/${where}/remove`);
}
