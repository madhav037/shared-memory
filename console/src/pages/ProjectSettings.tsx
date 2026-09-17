import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  CopyButton,
  Group,
  Loader,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import {
  addRepository,
  appointLead,
  fetchProject,
  grantAccess,
  removeLead,
  removeRepository,
  renameProject,
  restrictProject,
  revokeAccess,
  type ProjectDetail,
  type SignedInMember,
} from "../api/client";

/** Who looks after a project, which repositories belong to it, and what each one commits to reach it. */
export function ProjectSettings({ me }: { me: SignedInMember }) {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    const attempt = new AbortController();
    fetchProject(projectId, attempt.signal)
      .then(setProject)
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, [projectId]);

  const attempt = async (what: () => Promise<ProjectDetail>) => {
    try {
      setProject(await what());
      setRefused(null);
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  if (refused && project === null) return <Alert color="red">{refused}</Alert>;
  if (project === null) return <Loader size="sm" />;

  const runsTheTeam = me.role === "owner" || me.role === "admin";

  return (
    <Stack gap="md" maw={760}>
      <div>
        <Group gap="xs">
          <Title order={2} size="h3" data-testid="project-name">
            {project.name}
          </Title>
          {project.you_lead && (
            <Badge variant="light" color="teal">
              you lead this
            </Badge>
          )}
          {project.restricted && (
            <Badge variant="light" color="orange" data-testid="restricted">
              restricted
            </Badge>
          )}
        </Group>
        <Group gap="sm">
          <Code data-testid="project-id">{project.project_id}</Code>
          <Anchor component={Link} to={`/projects/${encodeURIComponent(project.project_id)}`} size="sm">
            Browse its memory
          </Anchor>
        </Group>
      </div>

      {refused && (
        <Alert color="red" data-testid="project-refused">
          {refused}
        </Alert>
      )}
      {!project.you_may_change && (
        <Text c="dimmed" size="sm" data-testid="read-only">
          Only this project’s leads and the team’s admins can change it.
        </Text>
      )}

      {project.you_may_change && (
        <Named name={project.name} onRenamed={(name) => attempt(() => renameProject(project.project_id, name))} />
      )}

      <Card withBorder>
        <Title order={3} size="h5" mb="xs">
          Project leads
        </Title>
        <Text c="dimmed" size="sm" mb="sm">
          A project lead looks after this project: its repositories, and who else leads it.
        </Text>
        <Stack gap="xs" data-testid="leads">
          {project.leads.length === 0 && <Text c="dimmed">Nobody leads this project.</Text>}
          {project.leads.map((lead) => (
            <Group key={lead.employee_id} justify="space-between">
              <Text>
                {lead.name} <Code>{lead.employee_id}</Code>
              </Text>
              {runsTheTeam && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  data-testid={`remove-lead-${lead.employee_id}`}
                  onClick={() => attempt(() => removeLead(project.project_id, lead.employee_id))}
                >
                  Take off
                </Button>
              )}
            </Group>
          ))}
        </Stack>
        {project.you_may_change && (
          <Adding
            label="Employee ID"
            placeholder="emp-2"
            action="Appoint a lead"
            testid="lead"
            onAdd={(employeeId) => attempt(() => appointLead(project.project_id, employeeId))}
          />
        )}
      </Card>

      <Card withBorder>
        <Group justify="space-between" align="start" mb="xs">
          <div>
            <Title order={3} size="h5">
              Who can reach it
            </Title>
            <Text c="dimmed" size="sm">
              {project.restricted
                ? "Restricted: only the members below, this project’s leads and the team’s admins can reach it."
                : "Open to the whole team. Restricting it keeps memory in this project to its access list."}
            </Text>
          </div>
          {project.you_may_change && (
            <Button
              variant="light"
              color={project.restricted ? "gray" : "orange"}
              data-testid="restrict"
              onClick={() => attempt(() => restrictProject(project.project_id, !project.restricted))}
            >
              {project.restricted ? "Open to the team" : "Restrict"}
            </Button>
          )}
        </Group>
        <Stack gap="xs" data-testid="access">
          {project.access.length === 0 && <Text c="dimmed">Nobody has been let in yet.</Text>}
          {project.access.map((member) => (
            <Group key={member.employee_id} justify="space-between">
              <Text>
                {member.name} <Code>{member.employee_id}</Code>
              </Text>
              {project.you_may_change && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  data-testid={`revoke-${member.employee_id}`}
                  onClick={() => attempt(() => revokeAccess(project.project_id, member.employee_id))}
                >
                  Take access away
                </Button>
              )}
            </Group>
          ))}
        </Stack>
        {project.you_may_change && (
          <Adding
            label="Employee ID"
            placeholder="emp-2"
            action="Let in"
            testid="access"
            onAdd={(employeeId) => attempt(() => grantAccess(project.project_id, employeeId))}
          />
        )}
        {!project.restricted && project.access.length > 0 && (
          <Text c="dimmed" size="sm" mt="sm">
            This list is kept while the project is open, so restricting it again lets the same members straight back
            in.
          </Text>
        )}
      </Card>

      <Card withBorder>
        <Title order={3} size="h5" mb="xs">
          Repositories
        </Title>
        <Text c="dimmed" size="sm" mb="sm">
          Each repository commits these settings into <Code>.claude/settings.json</Code>, which connects every session
          opened in it to this project.
        </Text>
        <Stack gap="md" data-testid="repositories">
          {project.repositories.length === 0 && <Text c="dimmed">No repositories yet.</Text>}
          {project.repositories.map((repository) => (
            <div key={repository.name}>
              <Group justify="space-between" mb="xs">
                <Text fw={500} data-testid={`repository-${repository.name}`}>
                  {repository.name}
                </Text>
                <Group gap="xs">
                  <CopyButton value={repository.settings}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="light" onClick={copy}>
                        {copied ? "Copied" : "Copy settings"}
                      </Button>
                    )}
                  </CopyButton>
                  {project.you_may_change && (
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="red"
                      data-testid={`remove-repository-${repository.name}`}
                      onClick={() => attempt(() => removeRepository(project.project_id, repository.name))}
                    >
                      Forget
                    </Button>
                  )}
                </Group>
              </Group>
              <Code block>{repository.settings}</Code>
            </div>
          ))}
        </Stack>
        {project.you_may_change && (
          <Adding
            label="Repository name"
            placeholder="billing-api"
            action="Add"
            testid="repository"
            onAdd={(name) => attempt(() => addRepository(project.project_id, name))}
          />
        )}
      </Card>
    </Stack>
  );
}

function Named({ name, onRenamed }: { name: string; onRenamed: (name: string) => void }) {
  const [asked, setAsked] = useState(name);

  return (
    <Card withBorder>
      <Group align="end" gap="sm">
        <TextInput
          label="Name"
          value={asked}
          data-testid="project-new-name"
          onChange={(event) => setAsked(event.currentTarget.value)}
        />
        <Button disabled={!asked.trim() || asked === name} data-testid="rename-project" onClick={() => onRenamed(asked)}>
          Rename
        </Button>
      </Group>
    </Card>
  );
}

function Adding({
  label,
  placeholder,
  action,
  testid,
  onAdd,
}: {
  label: string;
  placeholder: string;
  action: string;
  testid: string;
  onAdd: (value: string) => void;
}) {
  const [value, setValue] = useState("");

  return (
    <Group align="end" gap="sm" mt="md">
      <TextInput
        label={label}
        placeholder={placeholder}
        value={value}
        data-testid={`new-${testid}`}
        onChange={(event) => setValue(event.currentTarget.value)}
      />
      <Button
        disabled={!value.trim()}
        data-testid={`add-${testid}`}
        onClick={() => {
          onAdd(value.trim());
          setValue("");
        }}
      >
        {action}
      </Button>
    </Group>
  );
}
