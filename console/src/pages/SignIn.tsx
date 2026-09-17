import { Anchor, Button, Card, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import { signInUrl, type Status } from "../api/client";

/** The front door: sign in, or, once signed in, where to go next. */
export function SignIn({ status }: { status: Status }) {
  if (!status.member) {
    return (
      <Card withBorder maw={520}>
        <Stack gap="sm" align="flex-start">
          <Text data-testid="status">Connected to the Shared Memory server.</Text>
          {status.github_sign_in ? (
            <Button component="a" href={signInUrl} data-testid="sign-in">
              Sign in with GitHub
            </Button>
          ) : (
            <Text c="dimmed">Signing in with GitHub isn’t set up on this server yet.</Text>
          )}
        </Stack>
      </Card>
    );
  }
  return (
    <Card withBorder maw={520}>
      <Stack gap="sm" align="flex-start">
        <Text data-testid="status">
          Signed in as <strong>{status.member.name}</strong> ({status.member.employee_id}), {status.member.role} of team{" "}
          <strong>{status.member.team}</strong>.
        </Text>
        {status.member.role === "owner" && (
          <Anchor component={Link} to="/audit" data-testid="to-audit">
            Audit log
          </Anchor>
        )}
      </Stack>
    </Card>
  );
}
