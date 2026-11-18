import { describe, expect, it } from "vitest";

import { signInNote } from "./signIn";

describe("what the sign-in page says under its button", () => {
  it("says the console never asks for a personal token, once signing in is set up", () => {
    expect(signInNote({ github_sign_in: true, hosted: true })).toContain("the console never asks for it");
    expect(signInNote({ github_sign_in: true, hosted: false })).toContain("the console never asks for it");
  });

  it("names the platform's settings on a hosted server that isn't set up, as the server's refusal does", () => {
    const note = signInNote({ github_sign_in: false, hosted: true });

    expect(note).toContain("Signing in through the platform isn’t set up on this server yet");
    expect(note).toContain("the platform’s address, its public key and this server’s subdomain");
    expect(note).not.toContain("GitHub app");
  });

  it("names the GitHub app's details on a self-hosted server that isn't set up", () => {
    expect(signInNote({ github_sign_in: false, hosted: false })).toContain("the GitHub app’s details");
  });
});
