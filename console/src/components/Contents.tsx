import { IconChevronRight, IconLock, IconPin, IconScale } from "@tabler/icons-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { fetchFolder, fetchMembers, fetchProjects, type FileEntry, type Folder, type ProjectSummary } from "../api/client";
import { folderUrl, memoryUrl } from "../lib/format";

type ContentsState = {
  folders: Map<string, Folder>;
  projects: Map<string, ProjectSummary>;
  /** A member's name by their employee ID, and the ID itself for anyone not in the team. */
  nameOf: (employeeId: string) => string;
  expanded: Set<string>;
  load: (path: string) => void;
  toggle: (path: string) => void;
  refresh: () => void;
};

const Contents = createContext<ContentsState | null>(null);

/** Everything a member can reach, loaded a folder at a time and kept while they move around. */
export function ContentsProvider({ children }: { children: React.ReactNode }) {
  const [folders, setFolders] = useState<Map<string, Folder>>(new Map());
  const [projects, setProjects] = useState<Map<string, ProjectSummary>>(new Map());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const asking = useRef(new Set<string>());
  const location = useLocation();

  const load = useCallback((path: string) => {
    if (asking.current.has(path)) return;
    asking.current.add(path);
    fetchFolder(path)
      .then((folder) => setFolders((known) => new Map(known).set(path, folder)))
      .catch(() => undefined)
      .finally(() => asking.current.delete(path));
  }, []);

  const loadProjects = useCallback(() => {
    fetchProjects()
      .then((answer) => setProjects(new Map(answer.projects.map((one) => [one.project_id, one]))))
      .catch(() => undefined);
  }, []);

  const refresh = useCallback(() => {
    setFolders(new Map());
    loadProjects();
  }, [loadProjects]);

  useEffect(() => loadProjects(), [loadProjects]);
  useEffect(() => {
    fetchMembers()
      .then((team) => setNames(new Map(team.members.map((one) => [one.employee_id, one.name]))))
      .catch(() => undefined);
  }, []);
  const nameOf = useCallback((employeeId: string) => names.get(employeeId) ?? employeeId, [names]);

  // Follow the page: every folder above what is open is opened too.
  useEffect(() => {
    const here = currentPath(location.pathname, location.search);
    if (!here) return;
    const parts = here.split("/");
    const above: string[] = [];
    for (let depth = 1; depth < parts.length + (here.endsWith(".md") ? 0 : 1); depth += 1) {
      const path = parts.slice(0, depth).join("/");
      if (path !== "projects") above.push(path);
    }
    setExpanded((open) => {
      if (above.every((path) => open.has(path))) return open;
      const next = new Set(open);
      above.forEach((path) => next.add(path));
      return next;
    });
  }, [location.pathname, location.search]);

  const toggle = useCallback((path: string) => {
    setExpanded((open) => {
      const next = new Set(open);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ folders, projects, nameOf, expanded, load, toggle, refresh }),
    [folders, projects, nameOf, expanded, load, toggle, refresh],
  );
  return <Contents.Provider value={value}>{children}</Contents.Provider>;
}

export function useContents(): ContentsState {
  const state = useContext(Contents);
  if (!state) throw new Error("the contents are only known inside ContentsProvider");
  return state;
}

function currentPath(pathname: string, search: string): string | null {
  const asked = new URLSearchParams(search);
  if (pathname === "/files") return asked.get("folder");
  if (pathname === "/memory") return asked.get("path");
  return null;
}

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
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{name}</span>
          {project?.restricted && <IconLock size={13} stroke={1.8} aria-label="Restricted" />}
        </span>
        <span className="tally" aria-hidden>
          {tally}
        </span>
      </div>
      {open && (
        <ul role="group">
          {!folder && <li className="tree-note" style={{ "--depth": depth + 1 } as React.CSSProperties}>…</li>}
          {folder?.folders.map((sub) => (
            <FolderNode key={sub.path} path={sub.path} name={sub.name} tally={sub.memories} depth={depth + 1} onOpen={onOpen} />
          ))}
          {current.map((memory) => (
            <MemoryNode key={memory.path} memory={memory} depth={depth + 1} onOpen={onOpen} />
          ))}
          {cancelled.map((memory) => (
            <MemoryNode key={memory.path} memory={memory} depth={depth + 1} onOpen={onOpen} />
          ))}
          {folder && folder.folders.length === 0 && folder.memories.length === 0 && (
            <li className="tree-note" style={{ "--depth": depth + 1 } as React.CSSProperties}>
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
        title={memory.summary}
      >
        <span aria-hidden />
        <span className="label">{memory.title}</span>
        <span className="tally" aria-hidden style={{ display: "flex", gap: 4 }}>
          {memory.pinned && <IconPin size={13} stroke={1.8} />}
          {memory.challenged > 0 && <IconScale size={13} stroke={1.8} />}
        </span>
      </div>
    </li>
  );
}
