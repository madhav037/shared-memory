import { Alert, Button, Card, Group, Loader, Table, Text, TextInput, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";

import { fetchAudit, type AuditEvent, type AuditFilters, type SignedInMember } from "../api/client";

const WORDS: Record<string, string> = {
  signed_in: "signed in",
  sign_in_refused: "sign-in refused",
};

function when(at: string): string {
  return new Date(at).toLocaleString();
}

function describe(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([name, value]) => `${name}: ${String(value)}`)
    .join(", ");
}

/** Who changed what across the team, newest first. */
export function AuditLog({ member }: { member: SignedInMember }) {
  const [filters, setFilters] = useState<AuditFilters>({});
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    const attempt = new AbortController();
    setEvents(null);
    fetchAudit(filters, attempt.signal)
      .then((page) => {
        setEvents(page.events);
        setNext(page.next ?? null);
        setRefused(null);
      })
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) setRefused(problem.message);
      });
    return () => attempt.abort();
  }, [filters]);

  const older = useCallback(async () => {
    if (next === null) return;
    const page = await fetchAudit({ ...filters, before: next });
    setEvents((seen) => [...(seen ?? []), ...page.events]);
    setNext(page.next ?? null);
  }, [filters, next]);

  const filter = (name: keyof AuditFilters) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setFilters((was) => ({ ...was, [name]: event.currentTarget.value || undefined }));

  return (
    <>
      <Title order={2} size="h3" mb="xs">
        Audit log
      </Title>
      <Text c="dimmed" size="sm" mb="md">
        Everything that changed in team {member.team}, newest first.
      </Text>

      <Card withBorder mb="md">
        <Group align="end" gap="sm">
          <TextInput label="Member" placeholder="employee ID" data-testid="filter-member" onChange={filter("member")} />
          <TextInput label="Kind" placeholder="signed_in" data-testid="filter-kind" onChange={filter("kind")} />
          <TextInput label="From" type="date" data-testid="filter-since" onChange={filter("since")} />
          <TextInput label="To" type="date" data-testid="filter-until" onChange={filter("until")} />
        </Group>
      </Card>

      {refused && (
        <Alert color="red" data-testid="audit-refused">
          {refused}
        </Alert>
      )}
      {!refused && events === null && <Loader size="sm" />}
      {!refused && events?.length === 0 && (
        <Text c="dimmed" data-testid="audit-empty">
          Nothing matches those filters.
        </Text>
      )}
      {!refused && events && events.length > 0 && (
        <Table.ScrollContainer minWidth={600}>
          <Table striped highlightOnHover data-testid="audit-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>When</Table.Th>
                <Table.Th>Who</Table.Th>
                <Table.Th>What</Table.Th>
                <Table.Th>Details</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {events.map((event) => (
                <Table.Tr key={event.id}>
                  <Table.Td>{when(event.at)}</Table.Td>
                  <Table.Td>{event.actor}</Table.Td>
                  <Table.Td>{WORDS[event.kind] ?? event.kind}</Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {[event.project_id, event.target, describe(event.detail)].filter(Boolean).join(" · ")}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {next !== null && (
        <Button variant="default" mt="md" onClick={older} data-testid="audit-more">
          Show older
        </Button>
      )}
    </>
  );
}
