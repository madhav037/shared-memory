import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";

import { fetchFolder, fetchMembers, fetchProjects, type Folder, type ProjectSummary } from "../api/client";

/** Everything a member can reach: folders as they are opened, the projects they belong to, and who everyone is. */
export type ContentsState = {
  folders: Map<string, Folder>;
  projects: Map<string, ProjectSummary>;
  /** A member's name by their member ID, and the ID itself for anyone not in the team. */
  nameOf: (memberId: string) => string;
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
      .then((team) => setNames(new Map(team.members.map((one) => [one.member_id, one.name]))))
      .catch(() => undefined);
  }, []);
  const nameOf = useCallback((memberId: string) => names.get(memberId) ?? memberId, [names]);

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

/** What the page being looked at is showing: a folder, a memory, or neither. */
export function currentPath(pathname: string, search: string): string | null {
  const asked = new URLSearchParams(search);
  if (pathname === "/files") return asked.get("folder");
  if (pathname === "/memory") return asked.get("path");
  return null;
}
