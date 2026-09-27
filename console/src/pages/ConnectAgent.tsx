import { Button, CopyButton, Select } from "@mantine/core";
import { IconCheck, IconCopy, IconKey } from "@tabler/icons-react";
import { useState, type ReactNode } from "react";

import { fetchProject, reissueMyToken, type IssuedToken, type SignedInMember } from "../api/client";
import { Placeholder, Refusal } from "../components/Bits";
import { ConnectionFiles, EVERY_AGENT } from "../components/ConnectionFiles";
import { useContents } from "../lib/contents";
import { useAsked } from "../lib/useAsked";

/** What a member does in each coding agent, and what that agent then does with the team's memory by itself. */
const AGENTS: { name: string; steps: ReactNode[]; automatic: ReactNode }[] = [
  {
    name: "Claude Code",
    steps: [
      <>
        Open a repository that commits <code>.claude/settings.json</code> for its project, and let Claude Code enable
        the <code>shared-memory</code> plugin.
      </>,
      <>When the plugin asks, give it this server’s URL and your personal token. It keeps both in its settings.</>,
    ],
    automatic: <>Every session starts with the briefing, and memory that matches each prompt is recalled into it.</>,
  },
  {
    name: "Codex",
    steps: [
      <>
        Use Codex 0.78 or later (<code>codex --version</code>); earlier versions ignore a repository’s own
        configuration.
      </>,
      <>Set your personal token in <code>SHARED_MEMORY_TOKEN</code>, above.</>,
      <>
        Commit the repository’s <code>.codex/config.toml</code>, <code>AGENTS.md</code> section and skill.
      </>,
      <>Trust the project when Codex asks, so it reads the project’s own configuration.</>,
    ],
    automatic: (
      <>
        Every session starts with the briefing, and memory that matches each prompt is recalled into it. Codex reads
        the hooks from <code>.codex/config.toml</code> once you trust the project.
      </>
    ),
  },
  {
    name: "GitHub Copilot",
    steps: [
      <>
        Commit the repository’s <code>.vscode/mcp.json</code> for VS Code, and <code>.github/mcp.json</code> with
        <code>.github/hooks/shared-memory.json</code> for Copilot CLI, with the <code>AGENTS.md</code> section and
        skill.
      </>,
      <>VS Code asks for your personal token the first time and keeps it; Copilot CLI reads SHARED_MEMORY_TOKEN.</>,
      <>Trust the server when VS Code asks, and the folder when Copilot CLI asks.</>,
    ],
    automatic: (
      <>
        In Copilot CLI, every session starts with the briefing, which the server sends it directly. Recall on each
        prompt is not set up: the CLI drops whatever a prompt hook answers. VS Code has no hooks at all, so there
        Copilot calls <code>briefing</code> and <code>search</code> itself, as <code>AGENTS.md</code> asks.
      </>
    ),
  },
  {
    name: "Gemini CLI",
    steps: [
      <>Set your personal token in <code>SHARED_MEMORY_TOKEN</code>, above.</>,
      <>
        Commit the repository’s <code>.gemini/settings.json</code> and <code>.gemini/hooks/shared-memory.mjs</code>,
        with the <code>AGENTS.md</code> section and skill.
      </>,
      <>Trust the folder when Gemini CLI asks; it ignores a project’s settings until you do.</>,
    ],
    automatic: (
      <>
        Every session starts with the briefing, and memory that matches each prompt is recalled into it, through the
        small script in <code>.gemini/hooks</code> that both hooks run.
      </>
    ),
  },
  {
    name: "Cursor",
    steps: [
      <>Set your personal token in <code>SHARED_MEMORY_TOKEN</code>, above.</>,
      <>
        Commit the repository’s <code>.cursor/mcp.json</code>, <code>.cursor/hooks.json</code> and{" "}
        <code>.cursor/rules/shared-memory.mdc</code>, with the <code>AGENTS.md</code> section and skill.
      </>,
      <>Approve the server when Cursor asks.</>,
    ],
    automatic: (
      <>
        Every session starts with the briefing. Cursor’s prompt hook cannot add memory to a prompt, so the
        always-applied rule asks it to search memory before answering. On Windows, Cursor launches hooks through
        PowerShell, where the command doesn’t run, and the rule is what keeps memory in reach.
      </>
    ),
  },
  {
    name: "Devin Desktop",
    steps: [
      <>Set your personal token in <code>SHARED_MEMORY_TOKEN</code>, above.</>,
      <>
        Commit the repository’s <code>.devin/mcp_config.json</code> and <code>.devin/hooks.v1.json</code>, with the{" "}
        <code>AGENTS.md</code> section and skill.
      </>,
      <>
        If Devin connects without your token, put the same entry, with your own token, in{" "}
        <code>.devin/mcp_config.local.json</code>, which Devin keeps out of git. Its documentation doesn’t yet say it
        reads environment variables in headers.
      </>,
    ],
    automatic: (
      <>
        Every session starts with the briefing, and memory that matches each prompt is recalled into it, from Devin’s
        own hooks. Devin loads hooks from <code>.claude/settings.json</code> as well, where Shared Memory keeps none,
        so a session is never briefed twice.
      </>
    ),
  },
  {
    name: "Cline",
    steps: [
      <>Set your personal token in <code>SHARED_MEMORY_TOKEN</code>, above.</>,
      <>
        Cline keeps its servers on your machine, not in the repository: add the project’s entry to Cline’s MCP settings
        once, for each project you work in.
      </>,
      <>
        Commit the repository’s <code>AGENTS.md</code> section, which Cline reads, and the hook scripts in{" "}
        <code>.clinerules/hooks</code>. Make the ones without an extension executable (<code>chmod +x</code>).
      </>,
    ],
    automatic: (
      <>
        Every task starts with the briefing, and memory that matches each prompt is recalled into it, from the scripts
        in <code>.clinerules/hooks</code>. On macOS and Linux Cline runs the ones without an extension; on Windows it
        runs the <code>.ps1</code> beside them.
      </>
    ),
  },
];

/** How a member connects whichever coding agent they use, and where they get the token to do it with. */
export function ConnectAgent({ member }: { member: SignedInMember }) {
  const [agent, setAgent] = useState(AGENTS[0]!.name);
  const chosen = AGENTS.find((one) => one.name === agent) ?? AGENTS[0]!;

  return (
    <div className="narrow">
      <h1 className="page-title">Connect your agent</h1>
      <p className="standfirst">
        Every coding agent your team uses reads and writes the same memory. Connect yours with your personal token and
        a few small files the repository commits.
      </p>

      <Token member={member} />

      <h2 className="section-heading">Your agent</h2>
      <div className="view-switch" role="tablist" aria-label="Your coding agent">
        {AGENTS.map((one) => (
          <button
            key={one.name}
            type="button"
            role="tab"
            aria-selected={one.name === agent}
            onClick={() => setAgent(one.name)}
            data-testid={`connect-${one.name}`}
          >
            {one.name}
          </button>
        ))}
      </div>
      <ol className="steps" data-testid="agent-steps">
        {chosen.steps.map((step, place) => (
          <li key={place}>{step}</li>
        ))}
      </ol>
      <p className="agent-automatic">
        <span className="run-in">What happens by itself</span> {chosen.automatic}
      </p>

      <RepositoryFiles agent={chosen.name} />
    </div>
  );
}

/** Issue a personal token, shown once, and how to set it for every agent on this machine. */
function Token({ member }: { member: SignedInMember }) {
  const [issued, setIssued] = useState<IssuedToken | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [sure, setSure] = useState(false);
  const serverUrl = issued?.server_url ?? window.location.origin;

  const issue = async () => {
    setIssuing(true);
    try {
      setIssued(await reissueMyToken());
      setRefused(null);
    } catch (problem) {
      setRefused((problem as Error).message);
    } finally {
      setIssuing(false);
      setSure(false);
    }
  };

  return (
    <section aria-labelledby="token-heading">
      <h2 className="section-heading" id="token-heading">
        Your personal token
      </h2>
      <p className="section-lede">
        It proves which member a session belongs to. Set it once on each machine, in the{" "}
        <code>SHARED_MEMORY_TOKEN</code> environment variable, which most coding agents read; Claude Code and VS Code
        ask for it instead and keep it themselves. It never goes in a committed file. This server is at{" "}
        <code data-testid="server-url">{serverUrl}</code>.
      </p>
      {refused && <Refusal testid="token-refused">{refused}</Refusal>}

      {issued ? (
        <div className="issued appear" data-testid="issued-token" role="status">
          <b>Your new personal token</b>
          <code data-testid="token-value">{issued.personal_token}</code>
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
            This is the only time it is shown. Any token {member.member_id} had before has stopped working. Set it in
            your terminal’s profile with <code>export SHARED_MEMORY_TOKEN=…</code>, or on Windows with{" "}
            <code>setx SHARED_MEMORY_TOKEN …</code>, then restart your agent.
          </p>
        </div>
      ) : !sure ? (
        <Button leftSection={<IconKey size={16} stroke={1.6} />} onClick={() => setSure(true)} data-testid="issue-token">
          Issue a new personal token
        </Button>
      ) : (
        <div className="form-line" style={{ alignItems: "center" }}>
          <span style={{ fontSize: "0.9375rem" }}>
            The console never shows a token twice, and your current one stops working at once.
          </span>
          <Button loading={issuing} onClick={issue} data-testid="issue-token-confirm">
            Issue it
          </Button>
          <Button variant="default" onClick={() => setSure(false)}>
            Not now
          </Button>
        </div>
      )}
    </section>
  );
}

/** The files one of your repositories commits for the chosen agent, and the ones every agent shares. */
function RepositoryFiles({ agent }: { agent: string }) {
  const { projects } = useContents();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [repository, setRepository] = useState<string | null>(null);
  const project = projectId ?? [...projects.keys()][0] ?? null;
  const { answer: detail } = useAsked(
    (signal) => (project ? fetchProject(project, signal) : Promise.resolve(null)),
    [project],
  );
  const chosen = detail?.repositories.find((one) => one.name === repository) ?? detail?.repositories[0];

  return (
    <section aria-labelledby="files-heading">
      <h2 className="section-heading" id="files-heading">
        The repository’s files
      </h2>
      <p className="section-lede">
        Commit these once and everyone on the project gets them. A project lead can also copy them from the project’s
        settings.
      </p>
      <div className="form-line">
        <Select
          label="Project"
          data={[...projects.values()].map((one) => ({ value: one.project_id, label: one.name }))}
          value={project}
          onChange={(value) => {
            setProjectId(value);
            setRepository(null);
          }}
          allowDeselect={false}
          style={{ flex: "1 1 200px" }}
          data-testid="files-project"
        />
        <Select
          label="Repository"
          data={(detail?.repositories ?? []).map((one) => one.name)}
          value={chosen?.name ?? null}
          onChange={setRepository}
          allowDeselect={false}
          style={{ flex: "1 1 200px" }}
          data-testid="files-repository"
        />
      </div>
      {!project ? (
        <p className="empty">You aren’t in any project yet. Start one from the contents.</p>
      ) : !detail ? (
        <Placeholder lines={4} />
      ) : !chosen ? (
        <p className="empty">This project has no repositories yet. A project lead adds them in the project’s settings.</p>
      ) : (
        <ConnectionFiles
          key={`${chosen.name}-${agent}`}
          files={chosen.files.filter((file) => file.agent === agent || file.agent === EVERY_AGENT)}
          testid="agent-files"
        />
      )}
    </section>
  );
}
