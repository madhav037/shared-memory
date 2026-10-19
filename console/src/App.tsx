import { Drawer, Menu, TextInput, UnstyledButton, useMantineColorScheme } from "@mantine/core";
import {
  IconCheck,
  IconChevronDown,
  IconKey,
  IconLogout,
  IconMenu2,
  IconSearch,
} from "@tabler/icons-react";
import { useMediaQuery } from "@mantine/hooks";
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router";

import { fetchChallenges, fetchStatus, signInUrl, signOut, type SignedInMember, type Status } from "./api/client";
import { Refusal } from "./components/Bits";
import { ContentsTree } from "./components/Contents";
import { ContentsProvider } from "./lib/contents";
import { folderUrl, memoryUrl } from "./lib/format";
import { AuditLog } from "./pages/AuditLog";
import { BoardPage } from "./pages/BoardPage";
import { ConnectAgent } from "./pages/ConnectAgent";
import { Challenges } from "./pages/Challenges";
import { FolderPage } from "./pages/FolderPage";
import { ComingSoon, NotFound } from "./pages/Elsewhere";
import { Front } from "./pages/Front";
import { Landing } from "./pages/Landing";
import { MemoryPage } from "./pages/MemoryPage";
import { ProjectSettings } from "./pages/ProjectSettings";
import { SearchPage } from "./pages/SearchPage";
import { SessionsPage } from "./pages/SessionsPage";
import { Team } from "./pages/Team";

type Connection = { state: "asking" } | { state: "reached"; status: Status } | { state: "unreachable" };

/** A sign-in that was refused sends the member back here with the reason in the address. */
function refusal(): string | null {
  const reason = new URLSearchParams(window.location.search).get("sign-in-error");
  return reason && reason.trim() ? reason : null;
}

/**
 * The console's own addresses, as the signed-in routes below have them. A visitor who isn't signed in sees the
 * landing page, and its sign-in, at any of these; anywhere else is not found.
 */
const CONSOLE_ADDRESSES = [
  "/",
  "/files",
  "/memory",
  "/search",
  "/challenges",
  "/projects/*",
  "/team",
  "/audit",
  "/connect",
  "/my-token",
];

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
          <nav className="nav" aria-label="This page">
            <Link to="/#how">How it works</Link>
            <Link to="/#pricing">Pricing</Link>
          </nav>
          {status.github_sign_in && (
            <div className="masthead-end">
              <a className="quiet-link" href={signInUrl}>
                Sign in
              </a>
            </div>
          )}
        </header>
        <main id="page">
          <Routes>
            <Route path="/coming-soon" element={<ComingSoon />} />
            {CONSOLE_ADDRESSES.map((path) => (
              <Route key={path} path={path} element={<Landing status={status} refused={signInRefused} />} />
            ))}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </>
    );
  }

  return (
    <ContentsProvider>
      <SignedIn member={member} serverUrl={status.server_url} onLeave={leave} refused={signInRefused} />
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
  serverUrl,
  onLeave,
  refused,
}: {
  member: SignedInMember;
  serverUrl: string;
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
          {/* A word, not an icon: beside the menu's icon, a second icon read as a second menu. */}
          <UnstyledButton
            className="only-small masthead-contents"
            onClick={() => setContentsOpen(true)}
            data-testid="open-contents"
          >
            Contents
          </UnstyledButton>
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
            <Route
              path="/challenges"
              element={<Challenges readsAudit={readsAudit} onDecided={(left) => setWaiting(left.waiting.length)} />}
            />
            <Route path="/projects/:projectId/board" element={<BoardPage />} />
            <Route path="/projects/:projectId/sessions" element={<SessionsPage />} />
            <Route path="/projects/:projectId/settings" element={<ProjectSettings me={member} />} />
            <Route path="/projects/:projectId/memory" element={<OldMemoryAddress />} />
            <Route path="/projects/:projectId" element={<OldProjectAddress />} />
            <Route path="/team" element={<Team me={member} />} />
            <Route path="/audit" element={readsAudit ? <AuditLog member={member} /> : <Navigate to="/" replace />} />
            <Route path="/connect" element={<ConnectAgent serverUrl={serverUrl} />} />
            <Route path="/my-token" element={<Navigate to="/connect" replace />} />
            <Route path="/coming-soon" element={<ComingSoon inConsole />} />
            <Route path="*" element={<NotFound inConsole />} />
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
  // On a phone the menu holds the console's pages too, so its name says so, and carries the waiting challenges' count
  // that the folded nav can't show. The breakpoint is the stylesheet's.
  const small = useMediaQuery("(max-width: 900px)");
  const waiting = links.find((link) => link.to === "/challenges")?.count ?? 0;
  const waitingWords = `${waiting} ${waiting === 1 ? "challenge" : "challenges"} waiting`;
  return (
    <Menu position="bottom-end" width={260} withinPortal>
      <Menu.Target>
        <UnstyledButton
          data-testid="member-menu"
          aria-label={
            small
              ? `${member.name}: the console's pages, your token, appearance and signing out${waiting ? `. ${waitingWords}` : ""}`
              : `${member.name}: your token, appearance and signing out`
          }
          style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.9375rem", fontWeight: 600 }}
        >
          <span className="only-small" aria-hidden style={{ display: "inline-flex" }}>
            <IconMenu2 size={20} stroke={1.6} />
          </span>
          {waiting > 0 && (
            <span className="only-small count" aria-hidden data-testid="phone-waiting">
              {waiting}
            </span>
          )}
          <span data-testid="who" className="who">
            {member.name}
          </span>
          <IconChevronDown className="who-chevron" size={14} stroke={1.8} aria-hidden />
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>
          {member.name} ({member.member_id}), {member.role} of {member.team}
        </Menu.Label>
        <div className="only-small">
          {links.map((link) => (
            <Menu.Item
              key={link.to}
              onClick={() => goTo(link.to)}
              rightSection={
                link.count ? (
                  <span className="count" aria-label={`${link.count} waiting`}>
                    {link.count}
                  </span>
                ) : null
              }
            >
              {link.label}
            </Menu.Item>
          ))}
          <Menu.Divider />
        </div>
        <Menu.Item leftSection={<IconKey size={15} stroke={1.6} />} onClick={() => goTo("/connect")} data-testid="to-connect">
          Connect your agent
        </Menu.Item>
        <Menu.Divider />
        <Menu.Label>Appearance</Menu.Label>
        {(["auto", "light", "dark"] as const).map((scheme) => (
          <Menu.Item
            key={scheme}
            onClick={() => setColorScheme(scheme)}
            rightSection={colorScheme === scheme ? <IconCheck size={14} stroke={1.8} /> : null}
          >
            {scheme === "auto" ? "Match this computer" : scheme === "light" ? "Light" : "Dark"}
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
