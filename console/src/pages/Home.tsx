import { Alert, Anchor, Badge, Button, Card, Group, Loader, Stack, Text, TextInput, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";

import { createProject, fetchProjects, signInUrl, type ProjectSummary, type Status } from "../api/client";

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

  return (
    <Stack gap="md" w="100%" maw={720}>
      <NewProject />
      {projects.length === 0 ? (
        <Text c="dimmed" data-testid="no-projects">
          No projects yet. Create one here, or ask your Claude to with <code>create_project</code>.
        </Text>
      ) : (
        <Stack gap="xs" data-testid="projects">
          <Title order={2} size="h4">
            Projects
          </Title>
          {projects.map((project) => (
            <Card withBorder key={project.project_id} padding="sm" data-testid="project-card">
              <Group justify="space-between" wrap="nowrap" align="start">
                <div>
                  <Group gap="xs">
                    <Anchor component={Link} to={`/projects/${encodeURIComponent(project.project_id)}`}>
                      {project.name}
                    </Anchor>
                    {project.you_lead && (
                      <Badge size="xs" variant="light" color="teal">
                        you lead this
                      </Badge>
                    )}
                  </Group>
                  <Text size="sm" c="dimmed" data-testid={`leads-${project.project_id}`}>
                    {project.leads.length === 0
                      ? "No project lead"
                      : `Led by ${project.leads.map((lead) => lead.name).join(", ")}`}
                  </Text>
                </div>
                <Anchor component={Link} to={`/projects/${encodeURIComponent(project.project_id)}/settings`} size="sm">
                  Settings
                </Anchor>
              </Group>
            </Card>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

/** Creating a project here makes you its first project lead, exactly as create_project does in a session. */
function NewProject() {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const goTo = useNavigate();

  const create = async () => {
    setCreating(true);
    try {
      const project = await createProject(name);
      goTo(`/projects/${encodeURIComponent(project.project_id)}/settings`);
    } catch (problem) {
      setRefused((problem as Error).message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <Card withBorder padding="sm">
      {refused && (
        <Alert color="red" mb="sm" data-testid="new-project-refused">
          {refused}
        </Alert>
      )}
      <Group align="end" gap="sm">
        <TextInput
          label="New project"
          placeholder="Billing"
          value={name}
          data-testid="new-project-name"
          onChange={(event) => setName(event.currentTarget.value)}
        />
        <Button onClick={create} loading={creating} disabled={!name.trim()} data-testid="create-project">
          Create
        </Button>
      </Group>
    </Card>
  );
}
