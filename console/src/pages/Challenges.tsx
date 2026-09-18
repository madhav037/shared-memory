import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import {
  decideChallenge,
  fetchChallenges,
  type ChallengeDetail,
  type ChallengeList,
  type RaisedChallenge,
} from "../api/client";
import { memoryUrl } from "./Project";

function when(at: string): string {
  return new Date(at).toLocaleString();
}

/** Everything disputed: what is waiting for this member, and what they have asked of others. */
export function Challenges() {
  const { answer, refused, reload } = useChallenges();

  if (refused) return <Alert color="red">{refused}</Alert>;
  if (answer === null) return <Loader size="sm" />;

  return (
    <Stack gap="lg" maw={980}>
      <div>
        <Title order={2} size="h3">
          Challenges
        </Title>
        <Text c="dimmed" size="sm">
          A challenge asks the author of a memory to let it be superseded or retired.
        </Text>
      </div>
      <Waiting waiting={answer.waiting} onDecided={reload} empty="Nothing is waiting for your decision." />
      <Raised raised={answer.raised} />
    </Stack>
  );
}

/** What the console opens on: the challenges this member is being asked to decide. */
export function Waiting({
  waiting,
  onDecided,
  empty,
}: {
  waiting: ChallengeDetail[];
  onDecided: () => void;
  empty?: string;
}) {
  const [refused, setRefused] = useState<string | null>(null);

  if (waiting.length === 0) return empty ? <Text c="dimmed" data-testid="nothing-waiting">{empty}</Text> : null;

  const decide = async (challengeId: number, decision: "accept" | "reject") => {
    try {
      await decideChallenge(challengeId, decision);
      setRefused(null);
      onDecided();
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  // Several challenges can be against one memory; they are decided together, so they are shown together.
  const memories = new Map<string, ChallengeDetail[]>();
  for (const one of waiting) memories.set(one.target.path, [...(memories.get(one.target.path) ?? []), one]);

  return (
    <Stack gap="md" data-testid="waiting">
      <Title order={3} size="h5">
        Waiting for your decision
      </Title>
      {refused && (
        <Alert color="red" data-testid="decide-refused">
          {refused}
        </Alert>
      )}
      {[...memories].map(([path, against]) => {
        const first = against[0];
        if (!first) return null;
        return (
          <Card withBorder key={path}>
            <Group gap="xs" mb="xs">
              <Text fw={500}>{first.target.title}</Text>
              <Badge variant="light">{first.target.level} memory</Badge>
              {against.length > 1 && (
                <Badge color="orange" variant="light">
                  {against.length} challenges
                </Badge>
              )}
            </Group>
            {against.length > 1 && (
              <Text size="sm" c="dimmed" mb="sm">
                Accepting one of these closes the others, and whoever raised them is told why.
              </Text>
            )}
            <Stack gap="lg">
              {against.map((challenge) => (
                <div key={challenge.challenge_id}>
                  <Text size="sm" c="dimmed" mb="xs">
                    {challenge.raised_by} wants to {challenge.kind === "retire" ? "retire it" : "supersede it"} ·{" "}
                    {when(challenge.raised_at)}
                  </Text>
                  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                    <Side title="Now" memory={challenge.target} projectId={challenge.project_id} />
                    {challenge.challenger ? (
                      <Side title="Offered instead" memory={challenge.challenger} projectId={challenge.project_id} />
                    ) : (
                      <Card withBorder h="100%" padding="sm">
                        <Text size="sm" c="dimmed">
                          Nothing replaces it: {challenge.raised_by} says it is no longer true.
                        </Text>
                      </Card>
                    )}
                  </SimpleGrid>
                  <Group gap="xs" mt="sm">
                    <Button
                      size="xs"
                      data-testid={`accept-${challenge.challenge_id}`}
                      onClick={() => decide(challenge.challenge_id, "accept")}
                    >
                      Accept
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      data-testid={`reject-${challenge.challenge_id}`}
                      onClick={() => decide(challenge.challenge_id, "reject")}
                    >
                      Reject
                    </Button>
                  </Group>
                </div>
              ))}
            </Stack>
          </Card>
        );
      })}
    </Stack>
  );
}

function Side({
  title,
  memory,
  projectId,
}: {
  title: string;
  memory: ChallengeDetail["target"];
  projectId: string | null;
}) {
  return (
    <Card withBorder h="100%" padding="sm">
      <Text size="xs" tt="uppercase" c="dimmed" mb={4}>
        {title}
      </Text>
      {projectId && memory.status !== "gone" ? (
        <Anchor component={Link} to={memoryUrl(projectId, memory.path)} fw={500}>
          {memory.title}
        </Anchor>
      ) : (
        <Text fw={500}>{memory.title}</Text>
      )}
      <Text size="sm" c="dimmed" mb="xs">
        by {memory.author || "someone who has left"}
      </Text>
      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
        {memory.body}
      </Text>
    </Card>
  );
}

function Raised({ raised }: { raised: RaisedChallenge[] }) {
  if (raised.length === 0) return null;

  return (
    <Stack gap="xs">
      <Title order={3} size="h5">
        Challenges you raised
      </Title>
      <Table.ScrollContainer minWidth={640}>
        <Table striped data-testid="raised">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Raised</Table.Th>
              <Table.Th>Against</Table.Th>
              <Table.Th>Asking</Table.Th>
              <Table.Th>How it ended</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {raised.map((one) => (
              <Table.Tr key={one.challenge_id}>
                <Table.Td>{when(one.raised_at)}</Table.Td>
                <Table.Td>
                  <Code>{one.target_path}</Code>
                </Table.Td>
                <Table.Td>{one.kind === "retire" ? "to retire it" : "to supersede it"}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={STATES[one.state] ?? "gray"}>
                    {one.state}
                  </Badge>
                  {one.decided_by && (
                    <Text size="xs" c="dimmed">
                      by {one.decided_by}
                      {one.explanation ? ` — ${one.explanation}` : ""}
                    </Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

const STATES: Record<string, string> = {
  open: "blue",
  accepted: "green",
  rejected: "red",
  closed: "gray",
  withdrawn: "gray",
};

/** The challenges this member is part of, and a way to ask for them again after deciding one. */
export function useChallenges() {
  const [answer, setAnswer] = useState<ChallengeList | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [asked, setAsked] = useState(0);

  useEffect(() => {
    const attempt = new AbortController();
    fetchChallenges(attempt.signal)
      .then(setAnswer)
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, [asked]);

  const reload = useCallback(() => setAsked((times) => times + 1), []);
  return { answer, refused, reload };
}
