import { CopyButton } from "@mantine/core";
import { IconCheck, IconCopy } from "@tabler/icons-react";

import type { ConnectionFile } from "../api/client";

/** The files every coding agent shares, listed with each agent's own. */
export const EVERY_AGENT = "Every agent";

/** The files one repository commits for one coding agent, then the ones every agent shares: where each goes, how,
 * and what it says. The agent is chosen once for the page, not here. */
export function ConnectionFiles({ files, agent, testid }: { files: ConnectionFile[]; agent: string; testid?: string }) {
  const groups = [agent, EVERY_AGENT]
    .map((name) => ({ name, shown: files.filter((file) => file.agent === name) }))
    .filter((group) => group.shown.length > 0);

  return (
    <div className="connection-files" data-testid={testid}>
      {groups.length === 0 && <p className="connection-file-how">{agent} needs no files in this repository.</p>}
      {groups.map(({ name, shown }) => (
        <div key={name} className="connection-group" data-testid={`agent-${name}`}>
          {name === EVERY_AGENT && <p className="connection-group-name">And for every agent</p>}
          {shown.map((file) => (
            <div key={file.path} className="connection-file">
              <div className="connection-file-head">
                <code className="path">{file.path}</code>
                <span className="connection-file-action">
                  {file.kept_in === "machine"
                    ? "Once, on each member’s machine"
                    : file.action === "merge"
                      ? "Merge into it"
                      : "Create it"}
                </span>
                <CopyButton value={file.contents}>
                  {({ copied, copy }) => (
                    <button type="button" className="quiet-link" onClick={copy} data-testid={`copy-${file.path}`}>
                      {copied ? <IconCheck size={14} stroke={1.8} /> : <IconCopy size={14} stroke={1.6} />}
                      {copied ? "Copied" : "Copy"}
                    </button>
                  )}
                </CopyButton>
              </div>
              <p className="connection-file-how">{file.how}</p>
              {/* Focusable, so a file wider than the page scrolls from the keyboard too. */}
              <pre className="settings-block" tabIndex={0} role="region" aria-label={file.path}>
                {file.contents}
              </pre>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
