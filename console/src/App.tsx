import { useEffect, useState } from "react";

import { fetchStatus, type Status } from "./api/client";

type Connection = { state: "asking" } | { state: "reached"; status: Status } | { state: "unreachable" };

export function App() {
  const [connection, setConnection] = useState<Connection>({ state: "asking" });

  useEffect(() => {
    const attempt = new AbortController();
    fetchStatus(attempt.signal)
      .then((status) => setConnection({ state: "reached", status }))
      .catch(() => {
        if (!attempt.signal.aborted) setConnection({ state: "unreachable" });
      });
    return () => attempt.abort();
  }, []);

  return (
    <main>
      <h1>Shared Memory</h1>
      {connection.state === "asking" && <p data-testid="status">Reaching the server…</p>}
      {connection.state === "unreachable" && (
        <p data-testid="status" role="alert">
          Can’t reach the Shared Memory server. Check that it is running, then reload.
        </p>
      )}
      {connection.state === "reached" && (
        <>
          <p data-testid="status">Connected to the Shared Memory server.</p>
          <p>
            You are not signed in.{" "}
            {connection.status.github_sign_in
              ? "Sign in with GitHub to browse your team’s memory."
              : "Signing in with GitHub isn’t set up on this server yet."}
          </p>
        </>
      )}
    </main>
  );
}
