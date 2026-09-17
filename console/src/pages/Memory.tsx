import { Alert, Anchor, Badge, Button, Card, Group, Loader, Stack, Table, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { fetchMemory, pin, unpin, type MemoryDetail } from "../api/client";
import { History } from "./History";
import { memoryUrl } from "./Project";

const LEVELS: Record<string, string> = {
  project: "project memory",
  team: "team memory",
  personal: "personal memory",
};

/** One memory in full, as its author wrote it, with anything disputed about it. */
export function Memory() {
  const { projectId = "" } = useParams();
  const [asked] = useSearchParams();
  const path = asked.get("path") ?? "";
  const [memory, setMemory] = useState<MemoryDetail | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [pinRefused, setPinRefused] = useState<string | null>(null);

  useEffect(() => {
    const attempt = new AbortController();
    setMemory(null);
    setRefused(null);
    fetchMemory(projectId, path, attempt.signal)
      .then(setMemory)
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, [projectId, path]);

  if (refused) return <Alert color="red" data-testid="memory-refused">{refused}</Alert>;
  if (memory === null) return <Loader size="sm" />;

  return (
    <Stack gap="md" maw={760}>
      <div>
        <Anchor component={Link} to={`/projects/${encodeURIComponent(projectId)}`} size="sm">
          ← {projectId}
        </Anchor>
        <Title order={2} size="h3" mt="xs" data-testid="memory-title">
          {memory.title}
        </Title>
        <Text c="dimmed">{memory.summary}</Text>
      </div>

      <Group gap="xs">
        <Badge variant="light">{LEVELS[memory.level] ?? memory.level}</Badge>
        <Badge variant="light">{memory.type}</Badge>
        <Badge variant="light" color={memory.status === "active" ? "green" : "gray"}>
          {memory.status}
        </Badge>
        {memory.pinned && (
          <Badge variant="light" color="indigo" data-testid="pinned">
            pinned
          </Badge>
        )}
        <Text size="sm" c="dimmed">
          by {memory.author}
        </Text>
        {memory.level !== "personal" && (
          <Button
            size="compact-xs"
            variant={memory.pinned ? "subtle" : "light"}
            data-testid={memory.pinned ? "unpin" : "pin"}
            onClick={async () => {
              try {
                await (memory.pinned ? unpin : pin)(projectId, memory.path);
                setMemory({ ...memory, pinned: !memory.pinned });
                setPinRefused(null);
              } catch (problem) {
                setPinRefused((problem as Error).message);
              }
            }}
          >
            {memory.pinned ? "Unpin" : "Pin to every briefing"}
          </Button>
        )}
      </Group>

      {pinRefused && (
        <Alert color="red" data-testid="pin-refused">
          {pinRefused}
        </Alert>
      )}

      {memory.superseded_by && (
        <Alert color="gray" data-testid="superseded-by">
          Superseded by{" "}
          <Anchor component={Link} to={memoryUrl(projectId, memory.superseded_by)}>
            {memory.superseded_by}
          </Anchor>
        </Alert>
      )}
      {memory.open_challenges.length > 0 && (
        <Alert color="orange" title="Challenged" data-testid="open-challenges">
          <Stack gap={4}>
            {memory.open_challenges.map((challenge) => (
              <Text size="sm" key={challenge.challenge_id}>
                {challenge.raised_by} wants to {challenge.kind === "retire" ? "retire it" : "supersede it"}
                {challenge.challenger_path ? ` with ${challenge.challenger_path}` : ""}.
              </Text>
            ))}
          </Stack>
        </Alert>
      )}
      {memory.pending.length > 0 && (
        <Alert color="orange" title="Waiting on a decision" data-testid="pending">
          <Stack gap={4}>
            {memory.pending.map((challenge) => (
              <Text size="sm" key={challenge.challenge_id}>
                Offered to {challenge.kind === "retire" ? "retire" : "supersede"}
                {challenge.replaces ? ` ${challenge.replaces}` : ""}.
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      <Card withBorder>
        <Text style={{ whiteSpace: "pre-wrap" }} data-testid="memory-body">
          {memory.body}
        </Text>
      </Card>

      <Title order={3} size="h5" mt="md">
        History
      </Title>
      <History projectId={projectId} path={memory.path} />

      <Table variant="vertical" withTableBorder data-testid="memory-details">
        <Table.Tbody>
          <Detail name="Path" value={memory.path} />
          {memory.replaces && <Detail name="Replaces" value={memory.replaces} />}
          {memory.exception_to && <Detail name="Exception to" value={memory.exception_to} />}
          {memory.promoted_by && <Detail name="Promoted by" value={memory.promoted_by} />}
          {memory.related_files.length > 0 && <Detail name="Related files" value={memory.related_files.join(", ")} />}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function Detail({ name, value }: { name: string; value: string }) {
  return (
    <Table.Tr>
      <Table.Th w={160}>{name}</Table.Th>
      <Table.Td>
        <Text size="sm" ff="monospace">
          {value}
        </Text>
      </Table.Td>
    </Table.Tr>
  );
}
