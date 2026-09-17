import { Alert, Anchor, Badge, Card, Group, Loader, SegmentedControl, Stack, Text, TextInput, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { fetchTree, search, type SearchHit, type Tree } from "../api/client";

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

      {query ? (
        <Found projectId={projectId} query={query} level={level} />
      ) : (
        <Folders projectId={projectId} level={level} />
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

function Folders({ projectId, level }: { projectId: string; level: string }) {
  const { answer, refused } = useAsked<Tree>((signal) => fetchTree(projectId, level || undefined, signal), [
    projectId,
    level,
  ]);

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
      {answer.folders.map((folder) => (
        <Card withBorder key={folder.folder} padding="sm">
          <Text size="sm" c="dimmed" mb="xs" ff="monospace">
            {folder.folder}
          </Text>
          <Stack gap="xs">
            {folder.memories.map((memory) => (
              <div key={memory.path}>
                <Group gap="xs" wrap="nowrap">
                  <Anchor component={Link} to={memoryUrl(projectId, memory.path)}>
                    {memory.title}
                  </Anchor>
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
