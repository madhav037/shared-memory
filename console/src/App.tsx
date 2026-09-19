import { Drawer, Menu, TextInput, UnstyledButton, useMantineColorScheme } from "@mantine/core";
import {
  IconCheck,
  IconChevronDown,
  IconKey,
  IconListTree,
  IconLogout,
  IconMenu2,
  IconSearch,
} from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router";

import { fetchChallenges, fetchStatus, signOut, type SignedInMember, type Status } from "./api/client";
import { Refusal } from "./components/Bits";
import { ContentsProvider, ContentsTree } from "./components/Contents";
import { folderUrl, memoryUrl } from "./lib/format";
import { AuditLog } from "./pages/AuditLog";
import { Challenges } from "./pages/Challenges";
import { FolderPage } from "./pages/FolderPage";
import { Front, TitlePage } from "./pages/Front";
import { MemoryPage } from "./pages/MemoryPage";
import { MyToken } from "./pages/MyToken";
import { ProjectSettings } from "./pages/ProjectSettings";
import { SearchPage } from "./pages/SearchPage";
import { Team } from "./pages/Team";

type Connection = { state: "asking" } | { state: "reached"; status: Status } | { state: "unreachable" };

/** A sign-in that was refused sends the member back here with the reason in the address. */
function refusal(): string | null {
  const reason = new URLSearchParams(window.location.search).get("sign-in-error");
  return reason && reason.trim() ? reason : null;
}

export function App() {
  const [connection, setConnection] = useState<Connection>({ state: "asking" });
  const [signInRefused, setSignInRefused] = useState<string | null>(refusal);
  const goTo = useNavigate();

  useEffect(() => {
    const attempt = new AbortController();
    fetchStatus(attempt.signal)
      .then((status) => setConnection({ state: "reached", status }))
      .catch(() => {
        if (!attempt.signal.aborted) setConnection({ state: "unreachable" });
      });
    return () => attempt.abort();
  }, []);

  const leave = useCallback(async () => {
    const status = await signOut();
    setSignInRefused(null);
    setConnection({ state: "reached", status });
    goTo("/");
  }, [goTo]);

  if (connection.state === "asking") {
    return (
      <>
        <header className="masthead">
          <Wordmark team={null} />
        </header>
        <div className="title-page" data-testid="status" aria-busy="true" />
      </>
    );
  }

  if (connection.state === "unreachable") {
    return (
      <>
        <header className="masthead">
          <Wordmark team={null} />
        </header>
        <main className="title-page">
          <div className="title-page-inner" data-testid="status">
            <h1>Can’t reach the server</h1>
            <p>The Shared Memory server didn’t answer. Check that it is running, then reload this page.</p>
          </div>
        </main>
      </>
    );
  }

  const { status } = connection;
  const member = status.member;
  if (!member) {
    return (
      <>
        <header className="masthead">
          <Wordmark team={null} />
        </header>
        <main id="page">
          <TitlePage status={status} refused={signInRefused} />
        </main>
      </>
    );
  }

  return (
    <ContentsProvider>
      <SignedIn member={member} onLeave={leave} refused={signInRefused} />
    </ContentsProvider>
  );
}

function Wordmark({ team }: { team: string | null }) {
  return (
    <Link to="/" className="wordmark" aria-label="Shared Memory, contents">
      <i className="wordmark-mark" aria-hidden />
      <b>Shared Memory</b>
      {team && <span className="wordmark-team">{team}</span>}
    </Link>
  );
}

function SignedIn({
  member,
  onLeave,
  refused,
}: {
  member: SignedInMember;
  onLeave: () => void;
  refused: string | null;
}) {
  const [contentsOpen, setContentsOpen] = useState(false);
  const [waiting, setWaiting] = useState(0);
  const location = useLocation();
  const readsAudit = member.role === "owner" || member.role === "admin" || member.leads_a_project;

  useEffect(() => {
    const attempt = new AbortController();
    fetchChallenges(attempt.signal)
      .then((answer) => setWaiting(answer.waiting.length))
      .catch(() => undefined);
    return () => attempt.abort();
  }, [location.pathname, location.search]);

  const links = [
    { to: "/", label: "Contents", end: true, testid: "to-contents" },
    { to: "/search", label: "Search", testid: "to-search" },
    { to: "/challenges", label: "Challenges", count: waiting, testid: "to-challenges" },
    { to: "/team", label: "Team", testid: "to-team" },
    ...(readsAudit ? [{ to: "/audit", label: "Audit log", testid: "to-audit" }] : []),
  ];

  return (
    <>
      <a href="#page" className="skip">
        Skip to the page
      </a>
      <header className="masthead">
        <UnstyledButton
          className="only-small quiet-link"
          onClick={() => setContentsOpen(true)}
          aria-label="Open the contents"
          data-testid="open-contents"
        >
          <IconListTree size={20} stroke={1.6} />
        </UnstyledButton>
        <Wordmark team={member.team} />
        <nav className="nav" aria-label="The console">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end} data-testid={link.testid}>
              {link.label}
              {link.count ? (
                <span className="count" aria-label={`${link.count} waiting`}>
                  {link.count}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        <div className="masthead-end">
          {location.pathname !== "/search" && <MastheadSearch />}
          <Link to="/search" className="only-small quiet-link" aria-label="Search memory" data-testid="phone-search">
            <IconSearch size={20} stroke={1.6} />
          </Link>
          <MemberMenu member={member} onLeave={onLeave} links={links} />
        </div>
      </header>

      <Drawer
        opened={contentsOpen}
        onClose={() => setContentsOpen(false)}
        size="88%"
        title="Contents"
        styles={{ body: { padding: 0 }, content: { background: "var(--paper-2)" }, header: { background: "var(--paper-2)" } }}
      >
        <ContentsTree onOpen={() => setContentsOpen(false)} heading={false} />
      </Drawer>

      <div className="frame">
        <aside className="contents-column docked">
          <ContentsTree />
        </aside>
        <main className="page" id="page" tabIndex={-1}>
          {refused && <Refusal testid="sign-in-error">{refused}</Refusal>}
          <Routes>
            <Route path="/" element={<Front member={member} />} />
            <Route path="/files" element={<FolderPage member={member} />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/challenges" element={<Challenges />} />
            <Route path="/projects/:projectId/settings" element={<ProjectSettings me={member} />} />
            <Route path="/projects/:projectId/memory" element={<OldMemoryAddress />} />
            <Route path="/projects/:projectId" element={<OldProjectAddress />} />
            <Route path="/team" element={<Team me={member} />} />
            <Route path="/audit" element={readsAudit ? <AuditLog member={member} /> : <Navigate to="/" replace />} />
            <Route path="/my-token" element={<MyToken member={member} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </>
  );
}

function MastheadSearch() {
  const goTo = useNavigate();
  const [query, setQuery] = useState("");
  return (
    <form
      role="search"
      className="masthead-search"
      onSubmit={(event) => {
        event.preventDefault();
        if (query.trim()) goTo(`/search?q=${encodeURIComponent(query.trim())}`);
      }}
    >
      <TextInput
        size="sm"
        aria-label="Search memory"
        placeholder="Search memory"
        leftSection={<IconSearch size={15} stroke={1.6} aria-hidden />}
        value={query}
        onChange={(event) => setQuery(event.currentTarget.value)}
        data-testid="masthead-search"
      />
    </form>
  );
}

function MemberMenu({
  member,
  onLeave,
  links,
}: {
  member: SignedInMember;
  onLeave: () => void;
  links: { to: string; label: string; testid: string; count?: number }[];
}) {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const goTo = useNavigate();
  return (
    <Menu position="bottom-end" width={260} withinPortal>
      <Menu.Target>
        <UnstyledButton
          data-testid="member-menu"
          aria-label={`${member.name}: your token, appearance and signing out`}
          style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.9375rem", fontWeight: 600 }}
        >
          <span className="only-small" aria-hidden style={{ display: "inline-flex" }}>
            <IconMenu2 size={20} stroke={1.6} />
          </span>
          <span data-testid="who" className="who">
            {member.name}
          </span>
          <IconChevronDown className="who-chevron" size={14} stroke={1.8} aria-hidden />
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>
          {member.name} ({member.employee_id}), {member.role} of {member.team}
        </Menu.Label>
        <div className="only-small">
          {links.map((link) => (
            <Menu.Item key={link.to} onClick={() => goTo(link.to)}>
              {link.label}
              {link.count ? ` (${link.count})` : ""}
            </Menu.Item>
          ))}
          <Menu.Divider />
        </div>
        <Menu.Item leftSection={<IconKey size={15} stroke={1.6} />} onClick={() => goTo("/my-token")} data-testid="to-my-token">
          My personal token
        </Menu.Item>
        <Menu.Divider />
        <Menu.Label>Appearance</Menu.Label>
        {(["auto", "light", "dark"] as const).map((scheme) => (
          <Menu.Item
            key={scheme}
            onClick={() => setColorScheme(scheme)}
            rightSection={colorScheme === scheme ? <IconCheck size={14} stroke={1.8} /> : null}
          >
            {scheme === "auto" ? "Match this computer" : scheme === "light" ? "Printed page (light)" : "Bound volume (dark)"}
          </Menu.Item>
        ))}
        <Menu.Divider />
        <Menu.Item leftSection={<IconLogout size={15} stroke={1.6} />} onClick={onLeave} data-testid="sign-out">
          Sign out
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

/** Addresses from before the explorer still arrive where they meant to. */
function OldProjectAddress() {
  const { projectId = "" } = useParams();
  return <Navigate to={folderUrl(`projects/${projectId}`)} replace />;
}

function OldMemoryAddress() {
  const location = useLocation();
  const path = new URLSearchParams(location.search).get("path") ?? "";
  return <Navigate to={path ? memoryUrl(path) : "/"} replace />;
}
