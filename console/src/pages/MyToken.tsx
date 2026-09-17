import { Alert, Button, Card, Code, CopyButton, Group, List, Stack, Text, Title } from "@mantine/core";
import { useState } from "react";

import { reissueMyToken, type IssuedToken, type SignedInMember } from "../api/client";

/** How a member connects their own Claude Code, and where they get the token to do it with. */
export function MyToken({ member }: { member: SignedInMember }) {
  const [issued, setIssued] = useState<IssuedToken | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  const serverUrl = issued?.server_url ?? window.location.origin;

  const issue = async () => {
    setIssuing(true);
    try {
      setIssued(await reissueMyToken());
      setRefused(null);
    } catch (problem) {
      setRefused((problem as Error).message);
    } finally {
      setIssuing(false);
    }
  };

  return (
    <Stack gap="md" maw={720}>
      <div>
        <Title order={2} size="h3">
          Connect your Claude Code
        </Title>
        <Text c="dimmed">
          Your Claude sessions prove who you are with a <strong>personal token</strong>. It is yours alone, and it never
          goes anywhere but the plugin’s settings.
        </Text>
      </div>

      <Card withBorder>
        <List type="ordered" spacing="sm">
          <List.Item>
            Open a repository whose settings name a project, and let Claude Code enable the{" "}
            <Code>shared-memory</Code> plugin.
          </List.Item>
          <List.Item>
            When the plugin asks for the <strong>Shared Memory server URL</strong>, give it <Code>{serverUrl}</Code>.
          </List.Item>
          <List.Item>
            When it asks for your <strong>personal token</strong>, paste the one below.
          </List.Item>
        </List>
      </Card>

      {refused && (
        <Alert color="red" data-testid="token-refused">
          {refused}
        </Alert>
      )}

      {issued ? (
        <Alert color="green" title="Your new personal token" data-testid="issued-token">
          <Stack gap="xs" align="flex-start">
            <Code data-testid="token-value">{issued.personal_token}</Code>
            <Group gap="xs">
              <CopyButton value={issued.personal_token}>
                {({ copied, copy }) => (
                  <Button size="xs" variant="light" onClick={copy}>
                    {copied ? "Copied" : "Copy"}
                  </Button>
                )}
              </CopyButton>
            </Group>
            <Text size="sm">
              This is the only time it is shown. Any token {member.employee_id} had before has stopped working.
            </Text>
          </Stack>
        </Alert>
      ) : (
        <Card withBorder>
          <Stack gap="sm" align="flex-start">
            <Text size="sm" c="dimmed">
              Issuing a new token stops your current one working, so every Claude session of yours will need the new one.
            </Text>
            <Button onClick={issue} loading={issuing} data-testid="issue-token">
              Issue a new personal token
            </Button>
          </Stack>
        </Card>
      )}
    </Stack>
  );
}
