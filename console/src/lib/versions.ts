import type { MemoryVersion } from "../api/client";
import { day, moment } from "./format";

/**
 * What a version did to this memory, in words, from the record the server keeps of it. The server writes "Remember: …",
 * "Edit: …", "Promote: …", "Retire: …" and "Accept challenge 3: …", each naming the memory the change was made for; when
 * that is another memory, this one was superseded by it.
 */
export function whatHappened(version: MemoryVersion, title: string): string {
  const by = version.name + inAgent(version.agent);
  const message = version.message;
  const challenge = message.match(/^Accept challenge (\d+): (retire )?(.*)$/);
  if (challenge) {
    if (challenge[2]) return `Retired by ${by}, who accepted challenge ${challenge[1]}`;
    return challenge[3] === title
      ? `Took the place of the memory it challenged, when ${by} accepted challenge ${challenge[1]}`
      : `Superseded by “${challenge[3]}”, when ${by} accepted challenge ${challenge[1]}`;
  }
  const at = message.indexOf(": ");
  const verb = message.slice(0, at);
  const named = message.slice(at + 2);
  switch (verb) {
    case "Remember":
      return `First written by ${by}`;
    case "Edit":
      return `Amended by ${by}`;
    case "Promote":
      return named === title ? `Promoted by ${by}` : `Superseded by “${named}”, which ${by} promoted in its place`;
    case "Retire":
      return `Retired by ${by}`;
    default:
      return `${message}, by ${by}`;
  }
}

/**
 * When a version was the text: from the moment it was made until the next one. The latest is in force still,
 * unless the memory was retired or superseded, when the latest version is the one that cancelled it.
 */
export function inForce(versions: MemoryVersion[], place: number, standing = "active"): string {
  const version = versions[place];
  const next = versions[place + 1];
  if (!version) return "";
  if (!next && standing === "retired") return `Retired on ${moment(version.at)}`;
  if (!next && standing === "superseded") return `Superseded on ${moment(version.at)}`;
  if (!next) return `In force since ${moment(version.at)}`;
  if (moment(version.at) === moment(next.at)) return `In force for under a minute, on ${moment(version.at)}`;
  const sameDay = day(version.at) === day(next.at);
  const until = sameDay
    ? new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(next.at))
    : moment(next.at);
  return `In force from ${moment(version.at)} to ${until}`;
}

/** What the server records when a coding agent didn't say which one it is. */
export const ANOTHER_AGENT = "another agent";

/** Which coding agent a change came from, as a phrase to follow its author: " in Codex". Nothing when the server
 * recorded none, or only that it wasn't one it knows: "from another agent" reads as a fact the server doesn't have. */
export function inAgent(agent: string | null | undefined): string {
  if (!agent || agent === ANOTHER_AGENT) return "";
  return ` in ${agent}`;
}

/** The same, standing on its own: "In Codex", or nothing. */
export function agentLabel(agent: string): string {
  const phrase = inAgent(agent).trim();
  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}
