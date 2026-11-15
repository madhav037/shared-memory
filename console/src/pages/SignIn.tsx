import { Button } from "@mantine/core";
import { IconBrandGithub } from "@tabler/icons-react";

import { signInUrl, type Status } from "../api/client";
import { Refusal } from "../components/Bits";
import { PlatformLinks } from "../components/PlatformLinks";

/**
 * What a visitor who isn't signed in sees at any of the console's addresses: its sign-in, and nothing else. What
 * Shared Memory is and what it costs live on the platform.
 */
export function SignIn({ status, refused }: { status: Status; refused: string | null }) {
  return (
    <main className="title-page sign-in-page" id="page" data-testid="sign-in-page">
      <div className="title-page-inner">
        <h1>Sign in</h1>
        <p className="sign-in-lede">Read, search and govern your team’s memory.</p>
        {refused && (
          <Refusal testid="sign-in-error">
            <b>That sign-in didn’t work.</b> {refused}
          </Refusal>
        )}
        {status.github_sign_in && (
          <Button
            component="a"
            href={signInUrl}
            size="md"
            leftSection={<IconBrandGithub size={20} stroke={1.6} />}
            data-testid="sign-in"
          >
            Sign in with GitHub
          </Button>
        )}
        <p className="sign-in-fine" data-testid="status">
          {status.github_sign_in
            ? "Connected to the server. Your personal token stays with your coding agent; the console never asks for it."
            : "Connected to the server. Signing in with GitHub isn’t set up on this server yet: whoever runs it sets the GitHub app’s details."}
        </p>
        {status.platform_url && (
          <p className="sign-in-fine" data-testid="sign-in-notice">
            By signing in you agree to the <a href={`${status.platform_url}/terms`}>Terms</a> and accept the{" "}
            <a href={`${status.platform_url}/privacy`}>Privacy Policy</a>.
          </p>
        )}
        <PlatformLinks platformUrl={status.platform_url} />
      </div>
    </main>
  );
}
