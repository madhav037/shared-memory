import { CopyButton } from "@mantine/core";
import { IconCheck, IconCopy } from "@tabler/icons-react";
import { useState } from "react";

import type { ConnectionFile } from "../api/client";

/** The files one repository commits, one coding agent at a time: where each goes, how, and what it says. */
export function ConnectionFiles({ files, testid }: { files: ConnectionFile[]; testid?: string }) {
  const agents = [...new Set(files.map((file) => file.agent))];
  const [agent, setAgent] = useState(agents[0] ?? "");
  const shown = files.filter((file) => file.agent === agent);

  return (
    <div className="connection-files" data-testid={testid}>
      <div className="view-switch" role="tablist" aria-label="Which coding agent">
        {agents.map((one) => (
          <button
            key={one}
            type="button"
            role="tab"
            aria-selected={one === agent}
            onClick={() => setAgent(one)}
            data-testid={`agent-${one}`}
          >
            {one}
          </button>
        ))}
      </div>
      {shown.map((file) => (
        <div key={file.path} className="connection-file">
          <div className="connection-file-head">
            <code className="path">{file.path}</code>
            <span className="mark">
              {file.scope === "machine"
                ? "Once, on each member's machine"
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
          <pre className="settings-block">{file.contents}</pre>
        </div>
      ))}
    </div>
  );
}
