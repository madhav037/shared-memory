import { Alert, AppShell, Button, Group, Loader, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router";

import { fetchStatus, signOut, type Status } from "./api/client";
import { AuditLog } from "./pages/AuditLog";
import { SignIn } from "./pages/SignIn";

type Connection = { state: "asking" } | { state: "reached"; status: Status } | { state: "unreachable" };

/** A sign-in that was refused sends the member back here with the reason in the address. */
function refusal(): string | null {
  const reason = new URLSearchParams(window.location.search).get("sign-in-error");
  return reason && reason.trim() ? reason : null;
}

export function App() {
  const [connection, setConnection] = useState<Connection>({ state: "asking" });
  const [signInRefused, setSignInRefused] = useState<string | null>(refusal);
  const goTo = useNavigate();

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
    goTo("/");
  }, [goTo]);

  const member = connection.state === "reached" ? connection.status.member : null;

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Title order={1} size="h4">
            Shared Memory
          </Title>
          {member && (
            <Group gap="sm" wrap="nowrap">
              <Text size="sm" c="dimmed" visibleFrom="xs" data-testid="who">
                {member.name} · {member.team}
              </Text>
              <Button size="xs" variant="default" data-testid="sign-out" onClick={leave}>
                Sign out
              </Button>
            </Group>
          )}
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        {signInRefused && (
          <Alert color="red" mb="md" title="That sign-in didn’t work" data-testid="sign-in-error">
            {signInRefused}
          </Alert>
        )}
        {connection.state === "asking" && <Loader data-testid="status" size="sm" />}
        {connection.state === "unreachable" && (
          <Alert color="red" title="Can’t reach the server" data-testid="status">
            The Shared Memory server didn’t answer. Check that it is running, then reload.
          </Alert>
        )}
        {connection.state === "reached" && (
          <Routes>
            <Route path="/" element={<SignIn status={connection.status} />} />
            <Route path="/audit" element={member ? <AuditLog member={member} /> : <Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        )}
      </AppShell.Main>
    </AppShell>
  );
}
