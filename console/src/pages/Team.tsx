import { Button, CopyButton, Menu, NumberInput, Switch, TextInput, UnstyledButton } from "@mantine/core";
import { IconCheck, IconCopy, IconDots, IconUserPlus } from "@tabler/icons-react";
import { useState } from "react";

import {
  addMember,
  changeMember,
  changeRateLimits,
  fetchLicense,
  fetchMembers,
  fetchRateLimits,
  handOverOwnership,
  installLicense,
  reissueToken,
  removeMember,
  setAdmin,
  type IssuedToken,
  type LicenseState,
  type MemberSummary,
  type Members,
  type RateLimits,
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

  const attempt = async (what: () => Promise<Members>) => {
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
          <b>{members.find((one) => one.member_id === issued.member_id)?.name ?? issued.member_id}’s personal token</b>
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
            setAnswer(everyone);
          }}
          onRefused={setRefused}
        />
      )}

      <h2 className="section-heading">Members</h2>
      <p className="standfirst" data-testid="member-places">
        {answer.member_cap === null
          ? `${answer.members_used} members; this server has no member cap.`
          : `${answer.members_used} of ${answer.member_cap} places used.`}
      </p>
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

      <LicenseSection onRefused={setRefused} onInstalled={() => fetchMembers().then(setAnswer).catch(() => undefined)} />

      <RateLimitSection onRefused={setRefused} />

      {runs && (
        <section aria-labelledby="export-heading" data-testid="export">
          <h2 className="section-heading" id="export-heading">
            Take your data with you
          </h2>
          <p className="standfirst">
            One zip with the memory and its full history, the members, the projects and their cards, and the audit log.
            Downloading it is recorded in the audit log.
          </p>
          <Button component="a" href="/api/export" download data-testid="download-export">
            Download all team data
          </Button>
        </section>
      )}
    </div>
  );
}

/** Sent on the window when a license key is installed, so the banner above every page can ask again. */
export const LICENSE_CHANGED = "shared-memory:license-changed";

/** The words for where a license stands, shared by the Team page and the banner. */
export function licenseSentence(license: LicenseState): string {
  switch (license.status) {
    case "licensed":
      return `Licensed to ${license.team} until ${license.expires}.`;
    case "expiring":
      return `The license for ${license.team} expires on ${license.expires}, in ${license.days_left} days. Install a renewed key to keep the member cap.`;
    case "lapsed":
      return `The license for ${license.team} lapsed on ${license.expires}. Memory keeps working; install a renewed key to add members beyond the cap.`;
    case "read-only":
      return `The license for ${license.team} lapsed on ${license.expires}, so this hosted server is read-only: memory can be read but not changed. Paying for your team’s plan restores it.`;
    case "invalid":
      return `The license key can’t be used: ${license.reason}`;
    default:
      return "This server has no license key. It works fully for evaluation; install a key to license it for your team.";
  }
}

/** The server's license key: shown to every member, installed by admins. */
function LicenseSection({
  onRefused,
  onInstalled,
}: {
  onRefused: (message: string) => void;
  onInstalled: () => void;
}) {
  const { answer, setAnswer } = useAsked((signal) => fetchLicense(signal), []);
  const [key, setKey] = useState("");
  const [installing, setInstalling] = useState(false);

  if (!answer) return null;

  const install = async () => {
    setInstalling(true);
    try {
      setAnswer(await installLicense(key.trim()));
      window.dispatchEvent(new Event(LICENSE_CHANGED));
      onInstalled();
      setKey("");
      onRefused("");
    } catch (problem) {
      onRefused((problem as Error).message);
    } finally {
      setInstalling(false);
    }
  };

  return (
    <section aria-labelledby="license-heading" data-testid="license">
      <h2 className="section-heading" id="license-heading">
        License key
      </h2>
      <p className="standfirst" data-testid="license-status">
        {licenseSentence(answer)}
      </p>
      {answer.team && (
        <dl style={{ margin: "14px 0" }}>
          <dt>Team</dt>
          <dd data-testid="license-team">{answer.team}</dd>
          <dt>Member cap</dt>
          <dd data-testid="license-cap">{answer.member_cap}</dd>
          <dt>Expires</dt>
          <dd data-testid="license-expires">{answer.expires}</dd>
        </dl>
      )}
      {answer.you_may_change && (
        <div>
          <TextInput
            label="Install a license key"
            description="Paste the key you were sent. Or set SHARED_MEMORY_LICENSE_KEY in .env."
            value={key}
            onChange={(event) => setKey(event.currentTarget.value)}
            data-testid="license-key"
          />
          <Button mt="sm" onClick={install} loading={installing} disabled={!key.trim()} data-testid="install-license">
            Install key
          </Button>
        </div>
      )}
    </section>
  );
}

const LIMIT_FIELDS = [
  { key: "token_per_minute", label: "Each personal token", word: "token" },
  { key: "console_per_minute", label: "Each member’s console", word: "console" },
  { key: "address_per_minute", label: "Each address with no personal token", word: "address" },
] as const;

/** How many calls a minute the server lets each kind of caller make: shown to every member, changed by admins. */
function RateLimitSection({ onRefused }: { onRefused: (message: string) => void }) {
  const { answer, setAnswer } = useAsked((signal) => fetchRateLimits(signal), []);
  const [draft, setDraft] = useState<RateLimits | null>(null);
  const [saved, setSaved] = useState(false);
  if (!answer) return null;
  const shown = draft ?? answer;

  const save = async () => {
    try {
      const after = await changeRateLimits(shown);
      setAnswer(after);
      setDraft(null);
      setSaved(true);
      onRefused("");
    } catch (problem) {
      setSaved(false);
      onRefused((problem as Error).message);
    }
  };

  return (
    <section aria-labelledby="limits-heading" data-testid="rate-limits">
      <h2 className="section-heading" id="limits-heading">
        Rate limits
      </h2>
      <p className="section-lede">
        {answer.on
          ? "A caller that makes more calls a minute than this is told to wait, so one runaway coding agent can’t slow the server for everyone."
          : "Rate limits are switched off, so nothing is refused for making too many calls."}
      </p>
      <div className="scroll-x">
        <table className="register">
          <tbody>
            {LIMIT_FIELDS.map((field) => (
              <tr key={field.key}>
                <th scope="row">{field.label}</th>
                <td data-testid={`limit-${field.word}`}>{answer[field.key].toLocaleString("en")} calls a minute</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {answer.you_may_change && (
        <form
          className="form-line"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Switch
            label="Rate limits on"
            checked={shown.on}
            onChange={(event) => {
              setSaved(false);
              setDraft({ ...shown, on: event.currentTarget.checked });
            }}
            data-testid="rate-limit-on"
          />
          {LIMIT_FIELDS.map((field) => (
            <NumberInput
              key={field.key}
              label={field.label}
              min={1}
              allowDecimal={false}
              allowNegative={false}
              value={shown[field.key]}
              onChange={(value) => {
                setSaved(false);
                setDraft({ ...shown, [field.key]: typeof value === "number" ? value : 0 });
              }}
              data-testid={`rate-limit-${field.word}`}
              style={{ flex: "1 1 130px" }}
            />
          ))}
          <Button type="submit" data-testid="save-rate-limits">
            Save
          </Button>
          {saved && (
            <span role="status" data-testid="rate-limits-saved">
              Saved.
            </span>
          )}
        </form>
      )}
    </section>
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
  attempt: (what: () => Promise<Members>) => Promise<void>;
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
      <td data-label="Member ID" className="member-id">
        {id}
      </td>
      <td data-label="GitHub">
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
      <td data-label="Role" style={{ fontWeight: member.role === "member" ? 400 : 700, color: member.role === "member" ? undefined : "var(--ink)" }}>
        {ROLE_WORDS[member.role] ?? member.role}
      </td>
    </>
  );

  return (
    <>
      <tr className={member.removed ? "cancelled" : undefined}>
        {cells}
        {runs && (
          <td className="aside" style={{ textAlign: "right", paddingRight: 0 }}>
            {actionable && (
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <UnstyledButton
                    className="quiet-link row-menu"
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
  onAdded: (token: IssuedToken, everyone: Members) => void;
  onRefused: (message: string) => void;
}) {
  const [memberId, setMemberId] = useState("");
  const [name, setName] = useState("");
  const [github, setGithub] = useState("");
  const [adding, setAdding] = useState(false);
  const [missing, setMissing] = useState(false);

  const add = async () => {
    setAdding(true);
    try {
      const token = await addMember({ member_id: memberId.trim(), name: name.trim(), github: github.trim() || undefined });
      const everyone = await fetchMembers();
      onAdded(token, everyone);
      setMemberId("");
      setName("");
      setGithub("");
      setMissing(false);
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
          else setMissing(true);
        }}
      >
        <TextInput
          label="Member ID"
          placeholder="e.g. E1042"
          value={memberId}
          error={missing && !memberId.trim() ? "Enter their member ID." : undefined}
          data-testid="new-member-id"
          onChange={(event) => setMemberId(event.currentTarget.value)}
          style={{ flex: "1 1 130px" }}
        />
        <TextInput
          label="Name"
          value={name}
          error={missing && !name.trim() ? "Enter their name." : undefined}
          data-testid="new-name"
          onChange={(event) => setName(event.currentTarget.value)}
          style={{ flex: "2 1 180px" }}
        />
        <TextInput
          label="GitHub username"
          placeholder="e.g. dana-dev"
          value={github}
          data-testid="new-github"
          onChange={(event) => setGithub(event.currentTarget.value)}
          style={{ flex: "2 1 160px" }}
        />
        <Button
          type="submit"
          loading={adding}
          leftSection={<IconUserPlus size={16} stroke={1.6} />}
          data-testid="add-member"
        >
          Add member
        </Button>
      </form>
    </section>
  );
}
