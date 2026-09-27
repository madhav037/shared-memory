import { Button, CopyButton, Menu, TextInput, UnstyledButton } from "@mantine/core";
import { IconCheck, IconCopy, IconDots, IconUserPlus } from "@tabler/icons-react";
import { useState } from "react";

import {
  addMember,
  changeMember,
  fetchMembers,
  handOverOwnership,
  reissueToken,
  removeMember,
  setAdmin,
  type IssuedToken,
  type MemberSummary,
  type SignedInMember,
} from "../api/client";
import { Placeholder, Refusal } from "../components/Bits";
import { useAsked } from "../lib/useAsked";

const ROLE_WORDS: Record<string, string> = { owner: "Owner", admin: "Admin", member: "Member" };

type Editing =
  | { kind: "name" | "github"; memberId: string; value: string }
  | { kind: "remove" | "ownership"; memberId: string }
  | null;

/** Who is in the team, what each of them may do, and everything an admin does about that. */
export function Team({ me }: { me: SignedInMember }) {
  const { answer, refused: notListed, setAnswer } = useAsked((signal) => fetchMembers(signal), []);
  const [refused, setRefused] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedToken | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const runs = me.role === "owner" || me.role === "admin";

  const attempt = async (what: () => Promise<{ members: MemberSummary[] }>) => {
    try {
      const after = await what();
      setAnswer(after);
      setRefused(null);
      setEditing(null);
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  const issue = async (memberId: string) => {
    try {
      setIssued(await reissueToken(memberId));
      setRefused(null);
    } catch (problem) {
      setRefused((problem as Error).message);
    }
  };

  if (notListed) return <Refusal>{notListed}</Refusal>;
  if (!answer) return <Placeholder lines={8} />;
  const members = answer.members;
  const owner = members.find((one) => one.role === "owner");
  const admins = members.filter((one) => one.role === "admin" && !one.removed);

  return (
    <div className="column">
      <h1 className="page-title wide">Team {me.team}</h1>
      <p className="standfirst">
        {owner ? `${owner.name} owns the team` : "The team has an owner"}
        {admins.length > 0 ? `, with ${admins.map((one) => one.name).join(", ")} as admin${admins.length > 1 ? "s" : ""}` : ""}.{" "}
        {runs
          ? "Admins add and remove members and issue their tokens; only the owner decides who is an admin."
          : "Ask them to add someone, change access or issue a token."}
      </p>

      {refused && (
        <div style={{ marginTop: 20 }}>
          <Refusal testid="team-refused">{refused}</Refusal>
        </div>
      )}
      {issued && (
        <div className="issued appear" style={{ marginTop: 24 }} data-testid="new-member-token" role="status">
          <b>{issued.member_id}’s personal token</b>
          <code data-testid="new-member-token-value">{issued.personal_token}</code>
          <CopyButton value={issued.personal_token}>
            {({ copied, copy }) => (
              <Button
                size="xs"
                variant="default"
                onClick={copy}
                leftSection={copied ? <IconCheck size={14} stroke={1.8} /> : <IconCopy size={14} stroke={1.6} />}
              >
                {copied ? "Copied" : "Copy it"}
              </Button>
            )}
          </CopyButton>
          <p style={{ marginTop: 10 }}>
            Give it to them privately; it is shown only now. They can issue themselves a new one here in the console.
          </p>
        </div>
      )}

      {runs && (
        <AddMember
          onAdded={(token, everyone) => {
            setIssued(token);
            setAnswer({ members: everyone });
          }}
          onRefused={setRefused}
        />
      )}

      <h2 className="section-heading">Members</h2>
      <div className="scroll-x">
        <table className="register" data-testid="members">
          <thead>
            <tr>
              <th scope="col">Member</th>
              <th scope="col">Member ID</th>
              <th scope="col">GitHub</th>
              <th scope="col">Role</th>
              {runs && (
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <MemberRow
                key={member.member_id}
                member={member}
                me={me}
                runs={runs}
                editing={editing?.memberId === member.member_id ? editing : null}
                setEditing={setEditing}
                attempt={attempt}
                issue={issue}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MemberRow({
  member,
  me,
  runs,
  editing,
  setEditing,
  attempt,
  issue,
}: {
  member: MemberSummary;
  me: SignedInMember;
  runs: boolean;
  editing: Editing;
  setEditing: (editing: Editing) => void;
  attempt: (what: () => Promise<{ members: MemberSummary[] }>) => Promise<void>;
  issue: (memberId: string) => Promise<void>;
}) {
  const id = member.member_id;
  const actionable = runs && !member.removed && id !== me.member_id;
  const cells = (
    <>
      <td className="primary">
        {editing?.kind === "name" ? (
          <InlineEdit
            label="Name"
            value={editing.value}
            onChange={(value) => setEditing({ ...editing, value })}
            onSave={() => attempt(() => changeMember(id, { name: editing.value }))}
            onCancel={() => setEditing(null)}
          />
        ) : (
          <>
            {member.name}
            {id === me.member_id && <span style={{ color: "var(--ink-3)", fontWeight: 400 }}> (you)</span>}
            {member.removed && <span style={{ color: "var(--ink-3)", fontWeight: 400 }}> · removed</span>}
          </>
        )}
      </td>
      <td style={{ fontFamily: "var(--mono)", fontSize: "0.8125rem" }}>{id}</td>
      <td>
        {editing?.kind === "github" ? (
          <InlineEdit
            label="GitHub username"
            value={editing.value}
            onChange={(value) => setEditing({ ...editing, value })}
            onSave={() => attempt(() => changeMember(id, { github: editing.value }))}
            onCancel={() => setEditing(null)}
          />
        ) : member.github_login ? (
          `@${member.github_login}`
        ) : (
          <span style={{ color: "var(--ink-3)" }}>not linked</span>
        )}
      </td>
      <td style={{ fontWeight: member.role === "member" ? 400 : 700, color: member.role === "member" ? undefined : "var(--ink)" }}>
        {ROLE_WORDS[member.role] ?? member.role}
      </td>
    </>
  );

  return (
    <>
      <tr className={member.removed ? "cancelled" : undefined}>
        {cells}
        {runs && (
          <td style={{ textAlign: "right", paddingRight: 0 }}>
            {actionable && (
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <UnstyledButton
                    className="quiet-link"
                    aria-label={`What to do about ${member.name}`}
                    data-testid={`actions-${id}`}
                  >
                    <IconDots size={18} stroke={1.6} />
                  </UnstyledButton>
                </Menu.Target>
                <Menu.Dropdown>
                  {me.role === "owner" && member.role !== "owner" && (
                    <Menu.Item onClick={() => attempt(() => setAdmin(id, member.role !== "admin"))}>
                      {member.role === "admin" ? "Take admin away" : "Make an admin"}
                    </Menu.Item>
                  )}
                  {me.role === "owner" && (
                    <Menu.Item onClick={() => setEditing({ kind: "ownership", memberId: id })}>Hand over ownership…</Menu.Item>
                  )}
                  <Menu.Item onClick={() => issue(id)} data-testid={`reissue-${id}`}>
                    Issue a new personal token
                  </Menu.Item>
                  <Menu.Item onClick={() => setEditing({ kind: "name", memberId: id, value: member.name })}>
                    Correct their name
                  </Menu.Item>
                  <Menu.Item
                    onClick={() => setEditing({ kind: "github", memberId: id, value: member.github_login ?? "" })}
                  >
                    Change their GitHub account
                  </Menu.Item>
                  <Menu.Divider />
                  <Menu.Item
                    className="danger-item"
                    onClick={() => setEditing({ kind: "remove", memberId: id })}
                    data-testid={`remove-${id}`}
                  >
                    Remove from the team…
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
          </td>
        )}
      </tr>
      {(editing?.kind === "remove" || editing?.kind === "ownership") && (
        <tr>
          <td colSpan={5} style={{ background: "var(--paper-2)", padding: "12px 14px" }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: "0.875rem", color: "var(--ink)" }}>
                {editing.kind === "remove"
                  ? `Remove ${member.name}? Their token and console sessions stop working at once; their memories stay, credited to them.`
                  : `Make ${member.name} the owner? You stay an admin.`}
              </span>
              <Button
                size="xs"
                color={editing.kind === "remove" ? "red" : undefined}
                onClick={() => attempt(() => (editing.kind === "remove" ? removeMember(id) : handOverOwnership(id)))}
                data-testid={editing.kind === "remove" ? `remove-confirm-${id}` : `ownership-confirm-${id}`}
              >
                {editing.kind === "remove" ? "Remove them" : "Hand it over"}
              </Button>
              <Button size="xs" variant="default" onClick={() => setEditing(null)}>
                Keep things as they are
              </Button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function InlineEdit({
  label,
  value,
  onChange,
  onSave,
  onCancel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <form
      style={{ display: "flex", gap: 6, alignItems: "center" }}
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      <TextInput
        size="xs"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        autoFocus
        onKeyDown={(event) => event.key === "Escape" && onCancel()}
      />
      <Button size="xs" type="submit">
        Save
      </Button>
      <Button size="xs" variant="subtle" onClick={onCancel}>
        Cancel
      </Button>
    </form>
  );
}

function AddMember({
  onAdded,
  onRefused,
}: {
  onAdded: (token: IssuedToken, everyone: MemberSummary[]) => void;
  onRefused: (message: string) => void;
}) {
  const [memberId, setMemberId] = useState("");
  const [name, setName] = useState("");
  const [github, setGithub] = useState("");
  const [adding, setAdding] = useState(false);

  const add = async () => {
    setAdding(true);
    try {
      const token = await addMember({ member_id: memberId.trim(), name: name.trim(), github: github.trim() || undefined });
      const everyone = await fetchMembers();
      onAdded(token, everyone.members);
      setMemberId("");
      setName("");
      setGithub("");
    } catch (problem) {
      onRefused((problem as Error).message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <section aria-labelledby="add-heading">
      <h2 className="section-heading" id="add-heading">
        Add a member
      </h2>
      <p className="section-lede">
        Their personal token is shown once, here, to pass on privately. Their GitHub username lets them sign in to the
        console.
      </p>
      <form
        className="form-line"
        onSubmit={(event) => {
          event.preventDefault();
          if (memberId.trim() && name.trim()) void add();
        }}
      >
        <TextInput
          label="Member ID"
          placeholder="E1042"
          value={memberId}
          data-testid="new-member-id"
          onChange={(event) => setMemberId(event.currentTarget.value)}
          style={{ flex: "1 1 130px" }}
        />
        <TextInput
          label="Name"
          placeholder="Dana Dev"
          value={name}
          data-testid="new-name"
          onChange={(event) => setName(event.currentTarget.value)}
          style={{ flex: "2 1 180px" }}
        />
        <TextInput
          label="GitHub username"
          placeholder="dana-dev"
          value={github}
          data-testid="new-github"
          onChange={(event) => setGithub(event.currentTarget.value)}
          style={{ flex: "2 1 160px" }}
        />
        <Button
          type="submit"
          loading={adding}
          disabled={!memberId.trim() || !name.trim()}
          leftSection={<IconUserPlus size={16} stroke={1.6} />}
          data-testid="add-member"
        >
          Add member
        </Button>
      </form>
    </section>
  );
}
