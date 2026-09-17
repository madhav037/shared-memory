import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { fetchPins, fetchTree, pin, search, unpin, type Pins, type SearchHit, type Tree } from "../api/client";

const LEVELS = [
  { label: "Everything", value: "" },
  { label: "Project", value: "project" },
  { label: "Team", value: "team" },
  { label: "Personal", value: "personal" },
];

/** One project's memory: the folder tree, and a search across it. */
export function Project() {
  const { projectId = "" } = useParams();
  const [asked, setAsked] = useSearchParams();
  const level = asked.get("level") ?? "";
  const query = asked.get("q") ?? "";

  // Pinning changes both the pins and the tree's marks, so both reload when one of them changes.
  const [changed, setChanged] = useState(0);
  const changedNow = () => setChanged((times) => times + 1);

  const set = (name: string, value: string) => {
    const next = new URLSearchParams(asked);
    if (value) next.set(name, value);
    else next.delete(name);
    setAsked(next, { replace: true });
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="end" wrap="wrap">
        <Group gap="sm" align="baseline">
          <Title order={2} size="h4">
            {projectId}
          </Title>
          <Anchor component={Link} to={`/projects/${encodeURIComponent(projectId)}/settings`} size="sm">
            Settings
          </Anchor>
        </Group>
        <SegmentedControl
          size="xs"
          data={LEVELS}
          value={level}
          onChange={(chosen) => set("level", chosen)}
          data-testid="level"
        />
      </Group>

      <TextInput
        label="Search this project's memory"
        placeholder="which package manager do we use"
        defaultValue={query}
        data-testid="search"
        onChange={(event) => set("q", event.currentTarget.value)}
      />

      <Pinned projectId={projectId} changed={changed} onChanged={changedNow} />

      {query ? (
        <Found projectId={projectId} query={query} level={level} />
      ) : (
        <Folders projectId={projectId} level={level} changed={changed} onChanged={changedNow} />
      )}
    </Stack>
  );
}

function useAsked<T>(load: (signal: AbortSignal) => Promise<T>, on: unknown[]) {
  const [answer, setAnswer] = useState<T | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  useEffect(() => {
    const attempt = new AbortController();
    setAnswer(null);
    setRefused(null);
    load(attempt.signal)
      .then(setAnswer)
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, on);
  return { answer, refused };
}

/** Everything this project's sessions are briefed with, and how much of the cap it uses. */
function Pinned({
  projectId,
  changed,
  onChanged,
}: {
  projectId: string;
  changed: number;
  onChanged: () => void;
}) {
  const { answer } = useAsked<Pins>((signal) => fetchPins(projectId, signal), [projectId, changed]);
  const [refused, setRefused] = useState<string | null>(null);

  if (answer === null || answer.pins.length === 0) return null;

  return (
    <Card withBorder padding="sm" data-testid="pins">
      <Group justify="space-between" mb="xs">
        <Text fw={500}>In every briefing</Text>
        <Text size="sm" c="dimmed">
          about {answer.tokens} of {answer.cap} tokens
        </Text>
      </Group>
      {refused && (
        <Alert color="red" mb="xs">
          {refused}
        </Alert>
      )}
      <Stack gap="xs">
        {answer.pins.map((one) => (
          <Group key={one.path} justify="space-between" wrap="nowrap">
            <div>
              {one.kind === "memory" ? (
                <Anchor component={Link} to={memoryUrl(projectId, one.path)}>
                  {one.title}
                </Anchor>
              ) : (
                <Text>{one.title}</Text>
              )}
              <Text size="xs" c="dimmed" ff="monospace">
                {one.path} · {one.level} · about {one.tokens} tokens
              </Text>
            </div>
            <Button
              size="compact-xs"
              variant="subtle"
              data-testid={`unpin-${one.kind}`}
              onClick={async () => {
                try {
                  await unpin(projectId, one.path);
                  setRefused(null);
                  onChanged();
                } catch (problem) {
                  setRefused((problem as Error).message);
                }
              }}
            >
              Unpin
            </Button>
          </Group>
        ))}
      </Stack>
    </Card>
  );
}

function Folders({
  projectId,
  level,
  changed,
  onChanged,
}: {
  projectId: string;
  level: string;
  changed: number;
  onChanged: () => void;
}) {
  const { answer, refused } = useAsked<Tree>((signal) => fetchTree(projectId, level || undefined, signal), [
    projectId,
    level,
    changed,
  ]);
  const [pinRefused, setPinRefused] = useState<string | null>(null);

  const change = async (what: () => Promise<Pins>) => {
    try {
      await what();
      setPinRefused(null);
      onChanged();
    } catch (problem) {
      setPinRefused((problem as Error).message);
    }
  };

  if (refused) return <Alert color="red">{refused}</Alert>;
  if (answer === null) return <Loader size="sm" />;
  if (answer.folders.length === 0)
    return (
      <Text c="dimmed" data-testid="empty">
        No memory here yet.
      </Text>
    );

  return (
    <Stack gap="md" data-testid="tree">
      {pinRefused && (
        <Alert color="red" data-testid="pin-refused">
          {pinRefused}
        </Alert>
      )}
      {answer.folders.map((folder) => (
        <Card withBorder key={folder.folder} padding="sm">
          <Group justify="space-between" mb="xs" wrap="nowrap">
            <Text size="sm" c="dimmed" ff="monospace">
              {folder.folder}
            </Text>
            {folder.pinnable && (
              <Button
                size="compact-xs"
                variant="subtle"
                data-testid={folder.pinned ? "unpin-topic" : "pin-topic"}
                onClick={() =>
                  change(() => (folder.pinned ? unpin : pin)(projectId, folder.folder))
                }
              >
                {folder.pinned ? "Unpin this topic" : "Pin this topic"}
              </Button>
            )}
          </Group>
          <Stack gap="xs">
            {folder.memories.map((memory) => (
              <div key={memory.path}>
                <Group gap="xs" wrap="nowrap">
                  <Anchor component={Link} to={memoryUrl(projectId, memory.path)}>
                    {memory.title}
                  </Anchor>
                  {memory.pinned && (
                    <Badge size="xs" color="indigo">
                      pinned
                    </Badge>
                  )}
                  {memory.pending.length > 0 && (
                    <Badge size="xs" color="orange">
                      challenged
                    </Badge>
                  )}
                </Group>
                <Text size="sm" c="dimmed">
                  {memory.summary}
                </Text>
              </div>
            ))}
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}

function Found({ projectId, query, level }: { projectId: string; query: string; level: string }) {
  const { answer, refused } = useAsked<{ results: SearchHit[] }>(
    (signal) => search(projectId, { query, level: level || undefined }, signal),
    [projectId, query, level],
  );

  if (refused) return <Alert color="red">{refused}</Alert>;
  if (answer === null) return <Loader size="sm" />;
  if (answer.results.length === 0)
    return (
      <Text c="dimmed" data-testid="nothing-found">
        Nothing matches.
      </Text>
    );

  return (
    <Stack gap="xs" data-testid="results">
      {answer.results.map((hit) => (
        <Card withBorder key={`${hit.path}-${hit.heading}`} padding="sm">
          <Group gap="xs" wrap="nowrap">
            <Anchor component={Link} to={memoryUrl(projectId, hit.path)}>
              {hit.title}
            </Anchor>
            <Badge size="xs" variant="light">
              {hit.label}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {hit.summary}
          </Text>
        </Card>
      ))}
    </Stack>
  );
}

export function memoryUrl(projectId: string, path: string): string {
  return `/projects/${encodeURIComponent(projectId)}/memory?path=${encodeURIComponent(path)}`;
}
