import { Alert, Badge, Button, Card, Code, CopyButton, Group, Loader, Menu, Table, Text, TextInput, Title } from "@mantine/core";
import { useEffect, useState } from "react";

import {
  addMember,
  changeMember,
  fetchMembers,
  handOverOwnership,
  removeMember,
  setAdmin,
  type IssuedToken,
  type MemberSummary,
  type SignedInMember,
} from "../api/client";

/** Who is in the team, and everything an admin does about that. */
export function Team({ me }: { me: SignedInMember }) {
  const [members, setMembers] = useState<MemberSummary[] | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedToken | null>(null);

  useEffect(() => {
    const attempt = new AbortController();
    fetchMembers(attempt.signal)
      .then((answer) => setMembers(answer.members))
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, []);

  const attempt = async (what: () => Promise<{ members: MemberSummary[] }>) => {
    try {
      setMembers((await what()).members);
      setRefused(null);
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  if (refused && members === null) return <Alert color="red">{refused}</Alert>;
  if (members === null) return <Loader size="sm" />;

  return (
    <>
      <Title order={2} size="h3" mb="xs">
        Team {me.team}
      </Title>
      <Text c="dimmed" size="sm" mb="md">
        Admins add and remove members and issue their tokens. The owner decides who is an admin.
      </Text>

      {refused && (
        <Alert color="red" mb="md" data-testid="team-refused">
          {refused}
        </Alert>
      )}
      {issued && (
        <Alert color="green" title={`${issued.employee_id}’s personal token`} mb="md" data-testid="new-member-token">
          <Group gap="xs" align="center">
            <Code data-testid="new-member-token-value">{issued.personal_token}</Code>
            <CopyButton value={issued.personal_token}>
              {({ copied, copy }) => (
                <Button size="xs" variant="light" onClick={copy}>
                  {copied ? "Copied" : "Copy"}
                </Button>
              )}
            </CopyButton>
          </Group>
          <Text size="sm" mt="xs">
            Give it to them privately. It is shown only now — they can issue themselves a new one in the console.
          </Text>
        </Alert>
      )}

      <AddMember
        onAdded={(token, everyone) => {
          setIssued(token);
          setMembers(everyone);
        }}
        onRefused={setRefused}
      />

      <Table.ScrollContainer minWidth={640}>
        <Table striped highlightOnHover data-testid="members">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Member</Table.Th>
              <Table.Th>Employee ID</Table.Th>
              <Table.Th>GitHub</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {members.map((member) => (
              <Table.Tr key={member.employee_id} opacity={member.removed ? 0.55 : 1}>
                <Table.Td>
                  {member.name} {member.removed && <Badge size="xs">removed</Badge>}
                </Table.Td>
                <Table.Td>
                  <Code>{member.employee_id}</Code>
                </Table.Td>
                <Table.Td>{member.github_login ? `@${member.github_login}` : <Text c="dimmed">—</Text>}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={member.role === "owner" ? "indigo" : member.role === "admin" ? "teal" : "gray"}>
                    {member.role}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {!member.removed && member.employee_id !== me.employee_id && (
                    <Menu position="bottom-end" withinPortal>
                      <Menu.Target>
                        <Button size="compact-xs" variant="subtle" data-testid={`actions-${member.employee_id}`}>
                          Actions
                        </Button>
                      </Menu.Target>
                      <Menu.Dropdown>
                        {me.role === "owner" && member.role !== "owner" && (
                          <Menu.Item onClick={() => attempt(() => setAdmin(member.employee_id, member.role !== "admin"))}>
                            {member.role === "admin" ? "Take admin away" : "Make an admin"}
                          </Menu.Item>
                        )}
                        {me.role === "owner" && (
                          <Menu.Item onClick={() => attempt(() => handOverOwnership(member.employee_id))}>
                            Hand over ownership
                          </Menu.Item>
                        )}
                        <Menu.Item
                          onClick={() => {
                            const name = window.prompt("New name", member.name);
                            if (name) void attempt(() => changeMember(member.employee_id, { name }));
                          }}
                        >
                          Correct their name
                        </Menu.Item>
                        <Menu.Item
                          onClick={() => {
                            const github = window.prompt("GitHub username", member.github_login ?? "");
                            if (github !== null) void attempt(() => changeMember(member.employee_id, { github }));
                          }}
                        >
                          Change their GitHub account
                        </Menu.Item>
                        <Menu.Item
                          color="red"
                          data-testid={`remove-${member.employee_id}`}
                          onClick={() => attempt(() => removeMember(member.employee_id))}
                        >
                          Remove from the team
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}

function AddMember({
  onAdded,
  onRefused,
}: {
  onAdded: (token: IssuedToken, everyone: MemberSummary[]) => void;
  onRefused: (message: string) => void;
}) {
  const [employeeId, setEmployeeId] = useState("");
  const [name, setName] = useState("");
  const [github, setGithub] = useState("");
  const [adding, setAdding] = useState(false);

  const add = async () => {
    setAdding(true);
    try {
      const token = await addMember({ employee_id: employeeId, name, github: github || undefined });
      const everyone = await fetchMembers();
      onAdded(token, everyone.members);
      setEmployeeId("");
      setName("");
      setGithub("");
    } catch (problem) {
      onRefused((problem as Error).message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <Card withBorder mb="md">
      <Group align="end" gap="sm">
        <TextInput
          label="Employee ID"
          value={employeeId}
          data-testid="new-employee-id"
          onChange={(event) => setEmployeeId(event.currentTarget.value)}
        />
        <TextInput label="Name" value={name} data-testid="new-name" onChange={(event) => setName(event.currentTarget.value)} />
        <TextInput
          label="GitHub username"
          value={github}
          data-testid="new-github"
          onChange={(event) => setGithub(event.currentTarget.value)}
        />
        <Button onClick={add} loading={adding} disabled={!employeeId || !name} data-testid="add-member">
          Add member
        </Button>
      </Group>
    </Card>
  );
}
