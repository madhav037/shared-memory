import { Button, CopyButton } from "@mantine/core";
import { IconCheck, IconCopy, IconKey } from "@tabler/icons-react";
import { useState } from "react";

import { reissueMyToken, type IssuedToken, type SignedInMember } from "../api/client";
import { Refusal } from "../components/Bits";

/** How a member connects their own Claude Code, and where they get the token to do it with. */
export function MyToken({ member }: { member: SignedInMember }) {
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
    <div className="narrow">
      <h1 className="page-title">Connect your Claude Code</h1>
      <p className="standfirst">
        Your Claude sessions prove who you are with a personal token. It is yours alone, and it belongs in the plugin’s
        settings and nowhere else.
      </p>

      <h2 className="section-heading">Three steps</h2>
      <ol className="entries" style={{ counterReset: "step" }}>
        {[
          <>
            Open a repository whose settings name a project, and let Claude Code enable the <code>shared-memory</code>{" "}
            plugin.
          </>,
          <>
            When the plugin asks for the <b>Shared Memory server URL</b>, give it{" "}
            <code data-testid="server-url">{serverUrl}</code>.
          </>,
          <>
            When it asks for your <b>personal token</b>, paste a token issued below.
          </>,
        ].map((step, place) => (
          <li key={place} className="entry" style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 8 }}>
            <span style={{ fontFamily: "var(--serif)", fontWeight: 620, color: "var(--accent)" }}>{place + 1}.</span>
            <span style={{ fontSize: "0.9375rem", lineHeight: 1.6, color: "var(--ink)" }}>{step}</span>
          </li>
        ))}
      </ol>

      <h2 className="section-heading">Your personal token</h2>
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
            This is the only time it is shown. Any token {member.employee_id} had before has stopped working.
          </p>
        </div>
      ) : (
        <>
          <p className="section-lede">
            The console never shows a token twice. Issuing a new one stops your current one working, so every Claude
            session of yours will need the new one.
          </p>
          {!sure ? (
            <Button leftSection={<IconKey size={16} stroke={1.6} />} onClick={() => setSure(true)} data-testid="issue-token">
              Issue a new personal token
            </Button>
          ) : (
            <div className="form-line" style={{ alignItems: "center" }}>
              <span style={{ fontSize: "0.9375rem" }}>Your current token will stop working at once.</span>
              <Button loading={issuing} onClick={issue} data-testid="issue-token-confirm">
                Issue it
              </Button>
              <Button variant="default" onClick={() => setSure(false)}>
                Not now
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
