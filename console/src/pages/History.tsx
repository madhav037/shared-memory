import { Alert, Anchor, Card, Code, Group, Loader, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";

import { fetchDifference, fetchHistory, fetchVersion, type MemoryVersion } from "../api/client";

/** How a memory got to where it is: every version, what it said, and what changed. */
export function History({ projectId, path }: { projectId: string; path: string }) {
  const [versions, setVersions] = useState<MemoryVersion[] | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [showing, setShowing] = useState<{ commit: string; text: string } | null>(null);
  const [compared, setCompared] = useState<{ commit: string; difference: string } | null>(null);

  useEffect(() => {
    const attempt = new AbortController();
    setVersions(null);
    setShowing(null);
    setCompared(null);
    fetchHistory(projectId, path, attempt.signal)
      .then((history) => setVersions(history.versions))
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, [projectId, path]);

  const show = async (commit: string) => {
    setCompared(null);
    const version = await fetchVersion(projectId, path, commit);
    setShowing({ commit, text: version.text });
  };

  const compareWithEarlier = async (version: MemoryVersion, earlier: MemoryVersion) => {
    setShowing(null);
    const difference = await fetchDifference(projectId, path, earlier.commit, version.commit);
    setCompared({ commit: version.commit, difference: difference.difference });
  };

  if (refused) return <Alert color="red">{refused}</Alert>;
  if (versions === null) return <Loader size="sm" />;

  return (
    <Stack gap="sm" data-testid="history">
      {versions.map((version, place) => {
        const earlier = versions[place + 1];
        return (
          <Card withBorder key={version.commit} padding="sm">
            <Group justify="space-between" wrap="wrap" gap="xs">
              <div>
                <Text size="sm">{version.message}</Text>
                <Text size="xs" c="dimmed">
                  {version.name} ({version.author}) · {new Date(version.at).toLocaleString()} ·{" "}
                  <Code>{version.commit.slice(0, 8)}</Code>
                </Text>
              </div>
              <Group gap="xs">
                <Anchor component="button" type="button" size="sm" onClick={() => show(version.commit)}>
                  Read it
                </Anchor>
                {earlier && (
                  <Anchor
                    component="button"
                    type="button"
                    size="sm"
                    onClick={() => compareWithEarlier(version, earlier)}
                  >
                    What changed
                  </Anchor>
                )}
              </Group>
            </Group>

            {showing?.commit === version.commit && (
              <Card withBorder mt="sm" bg="var(--mantine-color-default-hover)">
                <Text size="sm" style={{ whiteSpace: "pre-wrap" }} ff="monospace" data-testid="version-text">
                  {showing.text}
                </Text>
              </Card>
            )}
            {compared?.commit === version.commit && (
              <Card withBorder mt="sm" bg="var(--mantine-color-default-hover)">
                <Difference difference={compared.difference} />
              </Card>
            )}
          </Card>
        );
      })}
      {versions.length === 0 && <Text c="dimmed">No history for this memory.</Text>}
    </Stack>
  );
}

function Difference({ difference }: { difference: string }) {
  return (
    <Stack gap={0} data-testid="difference">
      {difference.split("\n").map((line, place) => (
        <Text
          key={place}
          size="sm"
          ff="monospace"
          c={line.startsWith("+") && !line.startsWith("+++") ? "green" : line.startsWith("-") && !line.startsWith("---") ? "red" : "dimmed"}
          style={{ whiteSpace: "pre-wrap" }}
        >
          {line || " "}
        </Text>
      ))}
    </Stack>
  );
}
