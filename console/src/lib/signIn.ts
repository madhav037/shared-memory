import type { Status } from "../api/client";

/**
 * What the sign-in page says under its button: that the console never asks for a personal token or, on a server that
 * can't sign anyone in yet, what whoever runs it sets, in the server's own words. A hosted server's members sign in
 * through the platform, so it needs the platform's settings, not a GitHub app's.
 */
export function signInNote(status: Pick<Status, "github_sign_in" | "hosted">): string {
  if (status.github_sign_in) {
    return "Connected to the server. Your personal token stays with your coding agent; the console never asks for it.";
  }
  if (status.hosted) {
    return "Connected to the server. Signing in through the platform isn’t set up on this server yet: whoever runs it sets the platform’s address, its public key and this server’s subdomain.";
  }
  return "Connected to the server. Signing in with GitHub isn’t set up on this server yet: whoever runs it sets the GitHub app’s details.";
}
