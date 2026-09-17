import { useCallback, useEffect, useState } from "react";

import { fetchStatus, signInUrl, signOut, type Status } from "./api/client";

type Connection = { state: "asking" } | { state: "reached"; status: Status } | { state: "unreachable" };

/** A sign-in that was refused sends the member back here with the reason in the address. */
function refusal(): string | null {
  const reason = new URLSearchParams(window.location.search).get("sign-in-error");
  return reason && reason.trim() ? reason : null;
}

export function App() {
  const [connection, setConnection] = useState<Connection>({ state: "asking" });
  const [signInRefused, setSignInRefused] = useState<string | null>(refusal);

  useEffect(() => {
    const attempt = new AbortController();
    fetchStatus(attempt.signal)
      .then((status) => setConnection({ state: "reached", status }))
      .catch(() => {
        if (!attempt.signal.aborted) setConnection({ state: "unreachable" });
      });
    return () => attempt.abort();
  }, []);

  const leave = useCallback(async () => {
    const status = await signOut();
    setSignInRefused(null);
    setConnection({ state: "reached", status });
  }, []);

  return (
    <main>
      <h1>Shared Memory</h1>
      {signInRefused && (
        <p data-testid="sign-in-error" role="alert">
          {signInRefused}
        </p>
      )}
      {connection.state === "asking" && <p data-testid="status">Reaching the server…</p>}
      {connection.state === "unreachable" && (
        <p data-testid="status" role="alert">
          Can’t reach the Shared Memory server. Check that it is running, then reload.
        </p>
      )}
      {connection.state === "reached" && <SignedIn status={connection.status} onSignOut={leave} />}
    </main>
  );
}

function SignedIn({ status, onSignOut }: { status: Status; onSignOut: () => void }) {
  if (!status.member) {
    return (
      <>
        <p data-testid="status">Connected to the Shared Memory server.</p>
        {status.github_sign_in ? (
          <p>
            <a className="button" data-testid="sign-in" href={signInUrl}>
              Sign in with GitHub
            </a>
          </p>
        ) : (
          <p>Signing in with GitHub isn’t set up on this server yet.</p>
        )}
      </>
    );
  }
  return (
    <>
      <p data-testid="status">
        Signed in as <strong>{status.member.name}</strong> ({status.member.employee_id}), {status.member.role} of team{" "}
        <strong>{status.member.team}</strong>.
      </p>
      <p>
        <button type="button" data-testid="sign-out" onClick={onSignOut}>
          Sign out
        </button>
      </p>
    </>
  );
}
