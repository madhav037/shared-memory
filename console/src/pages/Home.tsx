import { Anchor, Button, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { fetchProjects, signInUrl, type ProjectSummary, type Status } from "../api/client";

/** The front door: sign in, then the projects whose memory you can read. */
export function Home({ status }: { status: Status }) {
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
    <Stack gap="md" align="flex-start">
      <Text data-testid="status">
        Signed in as <strong>{status.member.name}</strong> ({status.member.employee_id}), {status.member.role} of team{" "}
        <strong>{status.member.team}</strong>.
      </Text>
      <Projects />
    </Stack>
  );
}

function Projects() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    const attempt = new AbortController();
    fetchProjects(attempt.signal)
      .then((answer) => setProjects(answer.projects))
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, []);

  if (refused) return <Text c="red">{refused}</Text>;
  if (projects === null) return <Loader size="sm" />;
  if (projects.length === 0)
    return (
      <Text c="dimmed" data-testid="no-projects">
        No projects yet. Ask your Claude to create one with <code>create_project</code>.
      </Text>
    );

  return (
    <Stack gap="xs" w="100%" maw={640} data-testid="projects">
      <Title order={2} size="h4">
        Projects
      </Title>
      {projects.map((project) => (
        <Card withBorder key={project.project_id} padding="sm">
          <Group justify="space-between" wrap="nowrap">
            <Anchor component={Link} to={`/projects/${encodeURIComponent(project.project_id)}`}>
              {project.name}
            </Anchor>
            <Text size="sm" c="dimmed">
              {project.project_id}
            </Text>
          </Group>
        </Card>
      ))}
    </Stack>
  );
}
