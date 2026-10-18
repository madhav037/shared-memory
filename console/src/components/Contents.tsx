import { IconChevronRight, IconLock, IconPin, IconKey, IconScale } from "@tabler/icons-react";
import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { type FileEntry } from "../api/client";
import { currentPath, useContents } from "../lib/contents";
import { folderName, folderUrl, memoryUrl } from "../lib/format";

/** The contents column: team memory, then every project, each opening onto its folders and memories. */
export function ContentsTree({ onOpen, heading = true }: { onOpen?: () => void; heading?: boolean }) {
  const { folders, load } = useContents();
  const root = folders.get("");
  const tree = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!root) load("");
  }, [root, load]);

  const move = (event: React.KeyboardEvent) => {
    const items = Array.from(tree.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? []);
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (at < 0) return;
    const go = (index: number) => {
      const target = items[Math.max(0, Math.min(items.length - 1, index))];
      if (target) {
        items.forEach((item) => (item.tabIndex = -1));
        target.tabIndex = 0;
        target.focus();
      }
    };
    const item = items[at]!;
    if (event.key === "ArrowDown") go(at + 1);
    else if (event.key === "ArrowUp") go(at - 1);
    else if (event.key === "Home") go(0);
    else if (event.key === "End") go(items.length - 1);
    else if (event.key === "ArrowRight" && item.getAttribute("aria-expanded") === "false")
      item.dispatchEvent(new CustomEvent("toggle-row"));
    else if (event.key === "ArrowRight" && item.getAttribute("aria-expanded") === "true") go(at + 1);
    else if (event.key === "ArrowLeft" && item.getAttribute("aria-expanded") === "true")
      item.dispatchEvent(new CustomEvent("toggle-row"));
    else if (event.key === "ArrowLeft") {
      const parent = item.parentElement?.closest<HTMLElement>('[role="treeitem"]');
      if (parent) go(items.indexOf(parent));
    } else if (event.key === "Enter") item.dispatchEvent(new CustomEvent("open-row", { bubbles: false }));
    else return;
    event.preventDefault();
  };

  if (!root) {
    return (
      <div className="tree-note" style={{ paddingLeft: 20 }}>
        Opening the contents…
      </div>
    );
  }

  return (
    <nav aria-label="Contents">
      <div className={heading ? "contents-heading" : "visually-hidden"} id="contents-heading">
        Contents
      </div>
      <ul className="tree" role="tree" aria-labelledby="contents-heading" ref={tree} onKeyDown={move}>
        {root.folders.map((folder, place) => (
          <FolderNode
            key={folder.path}
            path={folder.path}
            name={folder.name}
            tally={folder.memories}
            depth={0}
            first={place === 0}
            onOpen={onOpen}
          />
        ))}
      </ul>
      {/* What a new member needs first, at the foot of what they can read. */}
      <p className="contents-foot">
        <span>New here? Your coding agent reads and writes this memory once it is connected.</span>
        <Link to="/connect" className="quiet-link" onClick={onOpen} data-testid="contents-connect">
          <IconKey size={14} stroke={1.6} aria-hidden />
          Connect your agent
        </Link>
      </p>
    </nav>
  );
}

function FolderNode({
  path,
  name,
  tally,
  depth,
  first = false,
  onOpen,
}: {
  path: string;
  name: string;
  tally: number;
  depth: number;
  first?: boolean;
  onOpen?: () => void;
}) {
  const { folders, projects, expanded, load, toggle } = useContents();
  const goTo = useNavigate();
  const location = useLocation();
  const open = expanded.has(path);
  const folder = folders.get(path);
  const here = currentPath(location.pathname, location.search) === path;
  const project = depth === 0 && path.startsWith("projects/") ? projects.get(path.split("/")[1]!) : undefined;
  const row = useRef<HTMLLIElement>(null);

  useEffect(() => {
    if (open && !folder) load(path);
  }, [open, folder, load, path]);

  useEffect(() => {
    const element = row.current;
    if (!element) return;
    const openRow = () => {
      goTo(folderUrl(path));
      onOpen?.();
    };
    const toggleRow = () => toggle(path);
    element.addEventListener("open-row", openRow);
    element.addEventListener("toggle-row", toggleRow);
    return () => {
      element.removeEventListener("open-row", openRow);
      element.removeEventListener("toggle-row", toggleRow);
    };
  }, [goTo, path, onOpen, toggle]);

  const current = folder?.memories.filter((memory) => memory.status === "active") ?? [];
  const cancelled = folder?.memories.filter((memory) => memory.status !== "active") ?? [];

  return (
    <li
      role="treeitem"
      aria-expanded={open}
      aria-level={depth + 1}
      aria-selected={here}
      aria-label={`${name}, ${tally} ${tally === 1 ? "memory" : "memories"}`}
      tabIndex={first ? 0 : -1}
      ref={row}
      className={depth === 0 ? "tree-group" : undefined}
    >
      <div
        className={depth === 0 ? "tree-row top" : "tree-row"}
        style={{ "--depth": depth } as React.CSSProperties}
        aria-current={here ? "page" : undefined}
        onClick={(event) => {
          event.stopPropagation();
          const onTwist = (event.target as HTMLElement).closest(".twist");
          if (onTwist) {
            toggle(path);
            return;
          }
          if (!open) toggle(path);
          goTo(folderUrl(path));
          onOpen?.();
        }}
      >
        <IconChevronRight className="twist" size={14} stroke={1.8} aria-hidden />
        <span className="label">
          <span className="label-text" title={name}>
            {name}
          </span>
          {project?.restricted && <IconLock size={13} stroke={1.8} aria-label="Restricted" />}
        </span>
        <span className="tally" aria-hidden>
          {tally}
        </span>
      </div>
      {open && (
        <ul role="group">
          {/* A note in a tree is neither a treeitem nor a list item: role none keeps it plain text. */}
          {!folder && (
            <li role="none" className="tree-note" style={{ "--depth": depth + 1 } as React.CSSProperties}>
              …
            </li>
          )}
          {folder?.folders.map((sub) => (
            <FolderNode key={sub.path} path={sub.path} name={folderName(sub.path, sub.name)} tally={sub.memories} depth={depth + 1} onOpen={onOpen} />
          ))}
          {current.map((memory) => (
            <MemoryNode key={memory.path} memory={memory} depth={depth + 1} onOpen={onOpen} />
          ))}
          {cancelled.map((memory) => (
            <MemoryNode key={memory.path} memory={memory} depth={depth + 1} onOpen={onOpen} />
          ))}
          {folder && folder.folders.length === 0 && folder.memories.length === 0 && (
            <li role="none" className="tree-note" style={{ "--depth": depth + 1 } as React.CSSProperties}>
              Nothing here yet
            </li>
          )}
        </ul>
      )}
    </li>
  );
}

function MemoryNode({ memory, depth, onOpen }: { memory: FileEntry; depth: number; onOpen?: () => void }) {
  const goTo = useNavigate();
  const location = useLocation();
  const here = currentPath(location.pathname, location.search) === memory.path;
  const row = useRef<HTMLLIElement>(null);
  const cancelled = memory.status !== "active";
  const open = () => {
    goTo(memoryUrl(memory.path));
    onOpen?.();
  };

  useEffect(() => {
    const element = row.current;
    if (!element) return;
    const openRow = () => {
      goTo(memoryUrl(memory.path));
      onOpen?.();
    };
    element.addEventListener("open-row", openRow);
    return () => element.removeEventListener("open-row", openRow);
  }, [goTo, memory.path, onOpen]);

  const standing = [
    memory.level === "personal" ? "personal memory" : null,
    cancelled ? memory.status : null,
    memory.pinned ? "pinned" : null,
    memory.challenged ? "challenged" : null,
  ].filter(Boolean);

  return (
    <li
      role="treeitem"
      aria-level={depth + 1}
      aria-selected={here}
      aria-label={[memory.title, ...standing].join(", ")}
      tabIndex={-1}
      ref={row}
    >
      <div
        className={["tree-row", "leaf", memory.level === "personal" ? "personal" : "", cancelled ? "cancelled" : ""].join(" ")}
        style={{ "--depth": depth } as React.CSSProperties}
        aria-current={here ? "page" : undefined}
        onClick={(event) => {
          event.stopPropagation();
          open();
        }}
        title={`${memory.title}\n${memory.summary}`}
      >
        <span aria-hidden />
        <span className="label">
          <span className="label-text">{memory.title}</span>
        </span>
        <span className="tally" aria-hidden style={{ display: "flex", gap: 4 }}>
          {memory.pinned && <IconPin size={13} stroke={1.8} />}
          {memory.challenged > 0 && <IconScale size={13} stroke={1.8} />}
        </span>
      </div>
    </li>
  );
}
