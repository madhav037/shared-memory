import { Alert, Anchor, AppShell, Button, Group, Loader, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router";

import { fetchStatus, signOut, type Status } from "./api/client";
import { AuditLog } from "./pages/AuditLog";
import { Challenges } from "./pages/Challenges";
import { Home } from "./pages/Home";
import { Memory } from "./pages/Memory";
import { MyToken } from "./pages/MyToken";
import { Project } from "./pages/Project";
import { ProjectSettings } from "./pages/ProjectSettings";
import { Team } from "./pages/Team";

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
          <Group gap="md" wrap="nowrap">
            <Anchor component={Link} to="/" underline="never" c="inherit">
              <Title order={1} size="h4">
                Shared Memory
              </Title>
            </Anchor>
            {member && (
              <>
                <Anchor component={Link} to="/challenges" size="sm" data-testid="to-challenges">
                  Challenges
                </Anchor>
                <Anchor component={Link} to="/my-token" size="sm" data-testid="to-my-token">
                  My token
                </Anchor>
              </>
            )}
            {(member?.role === "owner" || member?.role === "admin") && (
              <Anchor component={Link} to="/team" size="sm" data-testid="to-team">
                Team
              </Anchor>
            )}
            {(member?.role === "owner" || member?.role === "admin" || member?.leads_a_project) && (
              <Anchor component={Link} to="/audit" size="sm" data-testid="to-audit">
                Audit log
              </Anchor>
            )}
          </Group>
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
            <Route path="/" element={<Home status={connection.status} />} />
            <Route path="/projects/:projectId" element={member ? <Project /> : <Navigate to="/" replace />} />
            <Route
              path="/projects/:projectId/settings"
              element={member ? <ProjectSettings me={member} /> : <Navigate to="/" replace />}
            />
            <Route path="/projects/:projectId/memory" element={member ? <Memory /> : <Navigate to="/" replace />} />
            <Route path="/challenges" element={member ? <Challenges /> : <Navigate to="/" replace />} />
            <Route path="/my-token" element={member ? <MyToken member={member} /> : <Navigate to="/" replace />} />
            <Route path="/team" element={member ? <Team me={member} /> : <Navigate to="/" replace />} />
            <Route path="/audit" element={member ? <AuditLog member={member} /> : <Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        )}
      </AppShell.Main>
    </AppShell>
  );
}
