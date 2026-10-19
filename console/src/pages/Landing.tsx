import {
  IconArrowRight,
  IconBrandGithub,
  IconCircleCheck,
  IconLock,
  IconPencilOff,
  IconPlayerPlayFilled,
  IconPointerFilled,
  IconScale,
} from "@tabler/icons-react";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Link, useLocation } from "react-router";

import { signInUrl, type Status } from "../api/client";
import { Refusal } from "../components/Bits";
import { type Billing, type Hosting, money, PLAN_SIZES, planPrice, type PlanSize, TRIAL_DAYS } from "../lib/plans";
import "./landing.css";

/*
 * Before signing in: what Shared Memory is, shown working, and what it costs. Every person, memory and session
 * on this page is an example team's, and every scene is played by the page itself; nothing here reads the server
 * beyond the status it was given.
 */

const STROKE = 1.6;
const AGENTS = ["Claude Code", "Codex", "GitHub Copilot", "Gemini CLI", "Cursor", "Devin Desktop", "Cline"];

export function Landing({ status, refused }: { status: Status; refused: string | null }) {
  // A link to /#pricing from another page arrives here before the section exists, so the page scrolls itself.
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash]);

  return (
    <div className="landing">
      <section className="lp-hero">
        <div className="lp-wrap">
          <div className="lp-hero-top">
            <h1>
              <span className="lp-line">
                <span>What one agent learns,</span>
              </span>{" "}
              <span className="lp-line">
                <span>
                  <em>every</em> agent knows.
                </span>
              </span>
            </h1>
            {refused && (
              <Refusal testid="sign-in-error">
                <b>That sign-in didn’t work.</b> {refused}
              </Refusal>
            )}
            <p className="lp-standfirst">
              Shared Memory is one memory every coding agent on your team reads and writes, hosted by us or on your
              own server. Watch one finding travel.
            </p>
            <div className="lp-actions">
              <a className="lp-btn go" href="#pricing">
                Get it for your team <IconArrowRight size={18} stroke={2} />
              </a>
              {status.github_sign_in && (
                <a className="lp-btn on-night" href={signInUrl} data-testid="sign-in">
                  <IconBrandGithub size={20} stroke={STROKE} /> Sign in with GitHub
                </a>
              )}
            </div>
            <p className="lp-fine" data-testid="status">
              {status.github_sign_in
                ? "Connected to the server. Your personal token stays with your coding agent; the console never asks for it."
                : "Connected to the server. Signing in with GitHub isn’t set up on this server yet: whoever runs it sets the GitHub app’s details."}
            </p>
          </div>
          <Relay />
          <p className="lp-caption">An example team. Every session after Asha’s starts already knowing what she found.</p>
        </div>
      </section>

      <div className="lp-marquee" aria-label={`Works with ${AGENTS.slice(0, -1).join(", ")} and ${AGENTS.at(-1)}`}>
        <div className="track" aria-hidden="true">
          {[0, 1].map((copy) => (
            <ul key={copy}>
              {AGENTS.map((agent) => (
                <li key={agent}>{agent}</li>
              ))}
            </ul>
          ))}
        </div>
      </div>

      <section className="lp-sec" id="how">
        <div className="lp-wrap">
          <Heading>Learned once. Known everywhere.</Heading>
          <p className="lp-intro">
            Memory is written where it is learned, in the middle of real work, and reaches every other session without
            anyone copying it anywhere.
          </p>
          <Story />
        </div>
      </section>

      <section className="lp-sec tinted">
        <div className="lp-wrap">
          <Heading>Always clear whose word it is.</Heading>
          <p className="lp-intro">
            Every memory sits at a level, and the levels have a fixed order of weight. One member’s memory never passes
            for something the team agreed.
          </p>
          <Levels />
          <div className="lp-types" aria-label="Memory types">
            <span>Convention</span>
            <span>Decision</span>
            <span>Architecture</span>
            <span>Gotcha</span>
          </div>
        </div>
      </section>

      <section className="lp-sec">
        <div className="lp-wrap lp-two">
          <div>
            <Heading>Nothing is ever erased.</Heading>
            <p className="lp-intro">
              Memory is superseded or retired, never deleted, and every version keeps the name of who made it. Drag
              through a memory’s life and read it exactly as your agent read it on any day.
            </p>
          </div>
          <HistoryScene />
        </div>
      </section>

      <section className="lp-sec tinted">
        <div className="lp-wrap lp-two">
          <div>
            <Heading>Disagree? Challenge it.</Heading>
            <p className="lp-intro">
              Nobody changes another member’s memory. They raise a challenge with their reasoning, and the author
              decides, with what is offered in its place right beside it. Go on, decide this one.
            </p>
          </div>
          <ChallengeScene />
        </div>
      </section>

      <section className="lp-sec night">
        <div className="lp-wrap lp-two">
          <div>
            <Heading>Sessions see each other.</Heading>
            <p className="lp-intro">
              Each session says what it is working on and claims the files it edits. When two reach for the same file,
              both know before the work collides.
            </p>
            <ul className="lp-activity">
              <li>
                <span className="sq" style={{ background: "#4cc38a" }} />
                <b>Asha · Claude Code</b>Moving the billing jobs onto the new queue
              </li>
              <li>
                <span className="sq" style={{ background: "#ffb86b" }} />
                <b>Ben · Cursor</b>Retrying failed invoice emails
              </li>
            </ul>
          </div>
          <CollisionScene />
        </div>
      </section>

      <section className="lp-sec" id="console">
        <div className="lp-wrap">
          <Heading>A console to read it all.</Heading>
          <p className="lp-intro">
            Members sign in with GitHub and see exactly what their agents read, word for word. Whoever runs the team
            runs it from here too.
          </p>
          <ConsoleTour />
          <p className="lp-never">
            <IconPencilOff size={22} stroke={STROKE} aria-hidden />
            <span>
              <b>The console never writes memory.</b> Writing, editing and promoting stay in a session, where an agent
              can check them against everything the team already holds.
            </span>
          </p>
        </div>
      </section>

      <Pricing />

      <section className="lp-close">
        <div className="square" aria-hidden="true" />
        <div className="lp-wrap">
          <div>
            <h2>Give every agent your team’s memory.</h2>
            <p>
              Try it hosted by us for {TRIAL_DAYS} days, or self-host it with a license. Your members connect the coding
              agents they already use.
            </p>
          </div>
          <div className="lp-actions">
            <a className="lp-btn go" href="#pricing">
              Start a {TRIAL_DAYS}-day trial <IconArrowRight size={18} stroke={2} />
            </a>
            <a className="lp-btn plain" href="#pricing">
              Self-host it
            </a>
          </div>
        </div>
      </section>
      <footer className="lp-foot">
        <div className="lp-wrap">Memory kept as Markdown files on its server, every change in a git history.</div>
      </footer>
    </div>
  );
}

/* ---------- Motion helpers ---------- */

interface Run {
  stop: boolean;
}
/** One terminal line: its HTML, and whether it is typed out, after what prompt, and how long it holds. */
type Line = [html: string, opts?: { type?: boolean; prefix?: string; wait?: number }];

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const escapeHtml = (text: string) =>
  text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c] ?? c);
const PROMPT = '<span class="p">› </span>';

/** Writes lines into a terminal screen, typing the ones marked to be typed. Stops when the run does. */
async function play(screen: HTMLElement, lines: Line[], run: Run, speed = 22): Promise<void> {
  screen.innerHTML = "";
  for (const [html, opts = {}] of lines) {
    if (run.stop) return;
    const line = document.createElement("div");
    screen.append(line);
    if (opts.type && !reduced()) {
      const holder = document.createElement("div");
      holder.innerHTML = html;
      const text = holder.textContent ?? "";
      for (let i = 1; i <= text.length; i++) {
        if (run.stop) return;
        line.innerHTML = `${opts.prefix ?? ""}${escapeHtml(text.slice(0, i))}<span class="lp-caret"></span>`;
        await sleep(speed + Math.random() * 30);
      }
      line.innerHTML = (opts.prefix ?? "") + html;
      await sleep(250);
    } else {
      line.innerHTML = (opts.prefix ?? "") + html;
      if (!reduced()) await sleep(opts.wait ?? 380);
    }
  }
}

/** True once the element has been seen, and from then on. */
function useSeen<T extends Element>(threshold = 0.25): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element || seen) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { threshold },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [seen, threshold]);
  return [ref, seen];
}

/** A number that counts its way to each new value. */
function useCounted(target: number): number {
  const [shown, setShown] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    if (reduced()) {
      current.current = target;
      setShown(target);
      return;
    }
    const from = current.current;
    const started = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / 450);
      const value = Math.round(from + (target - from) * (1 - Math.pow(1 - progress, 4)));
      current.current = value;
      setShown(value);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return shown;
}

function Heading({ children }: { children: ReactNode }) {
  const [ref, seen] = useSeen<HTMLHeadingElement>();
  return (
    // The heading is watched and only its words are clipped: a heading clipped away entirely never counts as seen.
    <h2 ref={ref} className={seen ? "lp-wipe in" : "lp-wipe"}>
      <span>{children}</span>
    </h2>
  );
}

/* ---------- The relay: one finding reaching every session ---------- */

interface Wire {
  start: { x: number; y: number };
  end: { x: number; y: number };
  d: string;
}

/** A curve from one box's nearest edge to another's, in the relay's own coordinates. */
function wire(frame: HTMLElement, a: HTMLElement, b: HTMLElement): Wire {
  const r = frame.getBoundingClientRect();
  const A = a.getBoundingClientRect();
  const B = b.getBoundingClientRect();
  const ac = { x: A.left + A.width / 2 - r.left, y: A.top + A.height / 2 - r.top };
  const bc = { x: B.left + B.width / 2 - r.left, y: B.top + B.height / 2 - r.top };
  if (Math.abs(bc.x - ac.x) > Math.abs(bc.y - ac.y)) {
    const start = { x: (bc.x > ac.x ? A.right : A.left) - r.left, y: ac.y };
    const end = { x: (bc.x > ac.x ? B.left : B.right) - r.left, y: bc.y };
    const m = (start.x + end.x) / 2;
    return { start, end, d: `M${start.x},${start.y} C${m},${start.y} ${m},${end.y} ${end.x},${end.y}` };
  }
  const start = { x: ac.x, y: (bc.y > ac.y ? A.bottom : A.top) - r.top };
  const end = { x: bc.x, y: (bc.y > ac.y ? B.top : B.bottom) - r.top };
  const m = (start.y + end.y) / 2;
  return { start, end, d: `M${start.x},${start.y} C${start.x},${m} ${end.x},${m} ${end.x},${end.y}` };
}

async function fly(packet: HTMLElement, from: Wire["start"], to: Wire["end"], ms: number): Promise<void> {
  const w = packet.offsetWidth;
  const h = packet.offsetHeight;
  const flight = packet.animate(
    [
      { transform: `translate(${from.x - w / 2}px, ${from.y - h / 2}px) scale(0.9)`, opacity: 1 },
      { transform: `translate(${to.x - w / 2}px, ${to.y - h / 2}px) scale(1)`, opacity: 1 },
    ],
    { duration: ms, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "forwards" },
  );
  await flight.finished;
  flight.cancel();
}

const SOURCE_LINES: Line[] = [
  ["webhooks keep vanishing in the sandbox. why?", { type: true, prefix: PROMPT }],
  ['<span class="d">Reading the gateway logs…</span>', { wait: 700 }],
  ['Found it: the sandbox gateway <span class="b">drops payloads over 64 KB</span>, silently.', { wait: 900 }],
  ['<span class="d">remember →</span> saved as your personal memory', { wait: 700 }],
  ["promote it to project billing", { type: true, prefix: PROMPT }],
  ['<span class="d">checked against 31 memories:</span> <span class="ok">no contradictions</span>', { wait: 600 }],
  ['<span class="ok">Promoted.</span> Project memory, a gotcha.', { wait: 500 }],
];
const IDLE = '<span class="d">no session running</span>';
const WHEN = ["next morning", "an hour later", "the same afternoon"];
const briefed = (when: string) =>
  `<span class="d">session starts · briefing</span>\n<span class="new">The sandbox gateway drops webhooks over 64 KB</span>\n<span class="d">gotcha · Asha Rao · ${when}</span>`;

function Relay() {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const relay = root.current;
    if (!relay) return;
    const run: Run = { stop: false };
    const one = <T extends Element>(selector: string) => relay.querySelector<T>(selector) as T;
    const wires = one<SVGSVGElement>(".lp-wires");
    const hub = one<HTMLElement>(".lp-hub");
    const count = one<HTMLElement>(".lp-hub small");
    const source = one<HTMLElement>(".lp-pane.src");
    const sourceScreen = one<HTMLElement>(".lp-pane.src .lp-screen");
    const packet = one<HTMLElement>(".lp-packet");
    let receivers: HTMLElement[] = [];
    let links: Wire[] = [];
    let paths: SVGPathElement[] = [];

    const draw = () => {
      receivers = [...relay.querySelectorAll<HTMLElement>(".lp-pane.rx")].filter(
        (pane) => getComputedStyle(pane).display !== "none",
      );
      links = [wire(relay, source, hub), ...receivers.map((pane) => wire(relay, hub, pane))];
      wires.innerHTML = links.map((link) => `<path d="${link.d}"/>`).join("");
      paths = [...wires.querySelectorAll("path")];
    };
    const screenOf = (pane: HTMLElement) => pane.querySelector<HTMLElement>(".lp-screen") as HTMLElement;
    draw();
    window.addEventListener("resize", draw);

    const toHub = links[0];
    const loop = async () => {
      while (!run.stop && toHub) {
        receivers.forEach((pane) => {
          screenOf(pane).innerHTML = IDLE;
          pane.classList.remove("live", "lit");
        });
        paths.forEach((path) => path.classList.remove("flow"));
        count.textContent = "project billing";
        await play(sourceScreen, SOURCE_LINES, run, 28);
        if (run.stop) return;
        source.classList.add("lit");
        await sleep(300);
        paths[0]?.classList.add("flow");
        await fly(packet, toHub.start, toHub.end, 1100);
        if (run.stop) return;
        hub.classList.remove("pulse");
        void hub.offsetWidth;
        hub.classList.add("pulse");
        count.textContent = "+1 project memory";
        paths[0]?.classList.remove("flow");
        source.classList.remove("lit");
        await sleep(450);
        await Promise.all(
          receivers.map(async (pane, i) => {
            const out = links[i + 1];
            if (!out) return;
            const copy = packet.cloneNode(true) as HTMLElement;
            relay.append(copy);
            paths[i + 1]?.classList.add("flow");
            await sleep(i * 160);
            await fly(copy, out.start, out.end, 1000);
            copy.remove();
            paths[i + 1]?.classList.remove("flow");
            pane.classList.add("live", "lit");
            screenOf(pane).innerHTML = briefed(WHEN[i] ?? "later");
            setTimeout(() => pane.classList.remove("lit"), 1400);
          }),
        );
        await sleep(4200);
      }
    };

    if (reduced()) {
      sourceScreen.innerHTML = SOURCE_LINES.map(([html, opts]) => (opts?.prefix ?? "") + html).join("\n");
      receivers.forEach((pane, i) => {
        pane.classList.add("live");
        screenOf(pane).innerHTML = briefed(WHEN[i] ?? "later");
      });
    } else {
      void loop();
    }
    return () => {
      run.stop = true;
      window.removeEventListener("resize", draw);
    };
  }, []);

  return (
    <div
      className="lp-relay"
      ref={root}
      role="img"
      aria-label="A memory learned in Asha’s session reaches the sessions of Ben, Chen and Dana"
    >
      <svg className="lp-wires" aria-hidden="true" />
      <div className="lp-pane src live">
        <header>
          <span className="lp-dot" />
          Asha <span className="lp-who">· Claude Code</span>
        </header>
        <div className="lp-screen" />
      </div>
      <div className="lp-hub">
        <div>
          <div className="lp-mark" />
          Shared Memory
          <small>project billing</small>
        </div>
      </div>
      <div className="lp-receivers">
        {[
          ["Ben", "Cursor"],
          ["Chen", "Codex"],
          ["Dana", "Gemini CLI"],
        ].map(([who, agent]) => (
          <div className="lp-pane rx" key={who}>
            <header>
              <span className="lp-dot" />
              {who} <span className="lp-who">· {agent}</span>
            </header>
            <div className="lp-screen" />
          </div>
        ))}
      </div>
      <div className="lp-packet">
        The sandbox gateway drops webhooks over 64 KB <i>gotcha</i>
      </div>
    </div>
  );
}

/* ---------- How memory moves, played as the steps scroll past ---------- */

const STEPS = [
  {
    verb: "Save",
    title: "The agent remembers what it learned",
    text: "As a member’s personal memory: a convention, a decision, how the system is built, or a gotcha that would cost someone a day.",
    where: "During any session",
    who: "Asha · Claude Code",
    lines: [
      ["invoice numbers are given when an invoice is sent, not when it’s created. remember that.", { type: true, prefix: PROMPT }],
      ['<span class="d">remember →</span> saved as your <span class="b">personal memory</span>'],
      ['<span class="d">decision · Asha Rao · version 1</span>'],
    ] as Line[],
  },
  {
    verb: "Promote",
    title: "Checked before the team gets it",
    text: "Promoted to a project or the whole team, after the member’s agent compares it with what the team already holds and stops on a contradiction.",
    where: "During any session",
    who: "Asha · Claude Code",
    lines: [
      ["promote it to project billing", { type: true, prefix: PROMPT }],
      ['<span class="d">checking against what billing already holds…</span>', { wait: 600 }],
      ['<span class="r">Contradiction:</span> “Number invoices as soon as they’re created”'],
      ['<span class="d">project · Ben Okafor · v2</span>'],
      ['They can’t both be true. Supersede Ben’s memory? That raises a <span class="ok">challenge</span> for Ben to decide.'],
    ] as Line[],
  },
  {
    verb: "Brief",
    title: "Every session starts briefed",
    text: "The memories pinned for its project, and anything waiting for the member’s decision, arrive before the first prompt.",
    where: "As a session starts",
    who: "Ben · Cursor",
    lines: [
      ['<span class="d">session starts · briefing for</span> <span class="b">billing</span>'],
      ['<span class="ok">Pinned</span>  Release only through the release job'],
      ['<span class="ok">Pinned</span>  The sandbox gateway drops webhooks over 64 KB'],
      ['<span class="r">Waiting for you</span>  Asha challenges “Number invoices as soon as they’re created”'],
    ] as Line[],
  },
  {
    verb: "Recall",
    title: "The right memory, right when it matters",
    text: "Memories that match what the member asks are added to the prompt, so the agent knows them before it acts.",
    where: "As the member works",
    who: "Chen · Codex",
    lines: [
      ["two invoices got the same number. why?", { type: true, prefix: PROMPT }],
      ['<span class="d">recalled 2 memories for this prompt</span>'],
      ['<span class="new">Invoice numbers are given when an invoice is sent</span>'],
      ['<span class="d">decision · Asha Rao</span>'],
      ['Looking at <span class="b">send_invoice()</span> first, then.'],
    ] as Line[],
  },
];

function Story() {
  const [active, setActive] = useState(0);
  const steps = useRef<HTMLOListElement>(null);
  const screen = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const items = [...(steps.current?.children ?? [])];
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) if (entry.isIntersecting) setActive(items.indexOf(entry.target));
      },
      { rootMargin: "-45% 0px -45% 0px" },
    );
    items.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const run: Run = { stop: false };
    const lines = STEPS[active]?.lines;
    if (screen.current && lines) void play(screen.current, lines, run, 16);
    return () => {
      run.stop = true;
    };
  }, [active]);

  const [who, agent] = (STEPS[active]?.who ?? "").split(" · ");
  return (
    <div className="lp-story">
      <div className="lp-stage">
        <div className="lp-stage-bars" aria-hidden="true">
          {STEPS.map((step, i) => (
            <span key={step.verb} className={i <= active ? "on" : undefined} />
          ))}
        </div>
        <div className="lp-pane live" aria-hidden="true">
          <header>
            <span className="lp-dot" />
            {who} <span className="lp-who">· {agent}</span>
          </header>
          <div className="lp-screen" ref={screen} />
        </div>
      </div>
      <ol className="lp-steps" ref={steps}>
        {STEPS.map((step, i) => (
          <li key={step.verb} className={i === active ? "active" : undefined}>
            <div className="verb">{step.verb}</div>
            <h3>{step.title}</h3>
            <p>{step.text}</p>
            <span className="where">{step.where}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ---------- Levels ---------- */

function Levels() {
  const [ref, seen] = useSeen<HTMLDivElement>();
  return (
    <div className={seen ? "lp-stack in" : "lp-stack"} ref={ref}>
      <div className="lp-level project">
        <b>Project memory</b>
        <span>Holds for everyone on one project, and can make a deliberate exception to a team memory.</span>
        <span className="weight">weighs most</span>
      </div>
      <div className="lp-level">
        <b>Team memory</b>
        <span>Holds for every project in the team.</span>
        <span className="weight">then this</span>
      </div>
      <div className="lp-level personal">
        <b>Personal memory</b>
        <span>One member’s. The whole team can read it; nobody is bound by it until it is promoted.</span>
        <span className="weight">then this</span>
      </div>
      <div className="lp-level local">
        <b>Local memory</b>
        <span>An agent’s own memory on one machine. It never reaches the team.</span>
        <span className="weight">stays home</span>
      </div>
    </div>
  );
}

/* ---------- A memory's history, scrubbed ---------- */

const VERSIONS: { label: string; standing: ReactNode; past: boolean; currency: string; text: ReactNode }[] = [
  {
    label: "v1 · March",
    past: true,
    standing: (
      <>
        <b>As it stood on 3 March 2026:</b> version 1 of 3.
      </>
    ),
    currency: "Written by Asha Rao, 3 March 2026.",
    text: (
      <>
        Run <code>make release</code> from your laptop, after a dry run on staging.
      </>
    ),
  },
  {
    label: "v2 · May",
    past: true,
    standing: (
      <>
        <b>As it stood on 20 May 2026:</b> version 2 of 3.
      </>
    ),
    currency: "Amended by Asha Rao, 20 May 2026.",
    text: (
      <>
        Run <code>make release</code> <del>from your laptop, after a dry run on staging.</del>{" "}
        <ins>only from the release job, never from a laptop.</ins>
      </>
    ),
  },
  {
    label: "v3 · September",
    past: false,
    standing: (
      <>
        <b>In force.</b> Team memory, a convention. Version 3 of 3.
      </>
    ),
    currency: "Amended by Ben Okafor, 12 September 2026.",
    text: (
      <>
        Run <code>make release</code> only from the release job, never from a laptop.{" "}
        <ins>The job waits for the release before it to finish, so two releases never overlap.</ins>
      </>
    ),
  },
];

function HistoryScene() {
  const [version, setVersion] = useState(2);
  const [ref, seen] = useSeen<HTMLElement>(0.6);
  // Each play-through takes a number; choosing a version by hand takes the next, which ends any play-through.
  const turn = useRef(0);

  async function playThrough() {
    const mine = ++turn.current;
    for (const v of [0, 1, 2]) {
      if (turn.current !== mine) return;
      setVersion(v);
      await sleep(reduced() ? 0 : 2200);
    }
  }
  function choose(v: number) {
    turn.current++;
    setVersion(v);
  }

  useEffect(() => {
    if (seen) void playThrough();
  }, [seen]);

  const shown = VERSIONS[version];
  if (!shown) return null;
  return (
    <article className="lp-doc" ref={ref} data-testid="landing-history">
      <h3>Release only through the release job</h3>
      <div className={shown.past ? "status past" : "status"}>
        <IconCircleCheck size={18} stroke={STROKE} aria-hidden />
        <p>{shown.standing}</p>
      </div>
      <p className="lp-currency">{shown.currency}</p>
      <p className="text" key={version}>
        {shown.text}
      </p>
      <div className="lp-scrub">
        <div className="lp-scrub-row">
          <button className="lp-btn plain small" type="button" onClick={() => void playThrough()}>
            <IconPlayerPlayFilled size={14} /> Play
          </button>
          <input
            className="lp-range"
            type="range"
            min={0}
            max={2}
            step={1}
            value={version}
            aria-label="Version"
            aria-valuetext={shown.label}
            style={{ "--fill": `${version * 50}%` } as React.CSSProperties}
            onChange={(event) => choose(Number(event.target.value))}
          />
        </div>
        <div className="lp-ticks">
          {VERSIONS.map((v, i) => (
            <button key={v.label} type="button" aria-pressed={i === version} onClick={() => choose(i)}>
              {v.label}
            </button>
          ))}
        </div>
      </div>
    </article>
  );
}

/* ---------- A challenge, decided by the visitor ---------- */

function ChallengeScene() {
  const [decision, setDecision] = useState<"waiting" | "accepted" | "kept">("waiting");
  const card = useRef<HTMLDivElement>(null);

  function burst() {
    const host = card.current;
    if (!host || reduced()) return;
    const { width, height } = host.getBoundingClientRect();
    const colours = ["#00703c", "#4cc38a", "#ffdd00", "#111415"];
    for (let i = 0; i < 28; i++) {
      const bit = document.createElement("span");
      bit.className = "lp-confetti";
      bit.style.background = colours[i % colours.length] ?? "#00703c";
      bit.style.left = `${width * 0.5}px`;
      bit.style.top = `${height * 0.55}px`;
      host.append(bit);
      const angle = Math.random() * Math.PI * 2;
      const distance = 80 + Math.random() * 160;
      bit
        .animate(
          [
            { transform: "translate(0, 0) rotate(0)", opacity: 1 },
            {
              transform: `translate(${Math.cos(angle) * distance}px, ${Math.sin(angle) * distance + 60}px) rotate(${Math.random() * 540}deg)`,
              opacity: 0,
            },
          ],
          { duration: 900 + Math.random() * 500, easing: "cubic-bezier(0.16, 1, 0.3, 1)" },
        )
        .finished.then(() => bit.remove());
    }
  }

  const box =
    decision === "accepted" ? (
      <div className="status">
        <IconCircleCheck size={18} stroke={STROKE} aria-hidden />
        <p>
          <b>Superseded.</b> Asha’s memory is in force; yours stays in its history, struck through.
        </p>
      </div>
    ) : decision === "kept" ? (
      <div className="status cancelled">
        <IconCircleCheck size={18} stroke={STROKE} aria-hidden />
        <p>
          <b>Kept.</b> Your memory stands. Asha sees your decision, and the challenge stays on record.
        </p>
      </div>
    ) : (
      <div className="status challenged">
        <IconScale className="scales" size={18} stroke={STROKE} aria-hidden />
        <p>
          <b>Challenged.</b> Asha asks to supersede your memory. It’s your call.
        </p>
      </div>
    );

  return (
    <div
      className={decision === "waiting" ? "lp-challenge" : `lp-challenge ${decision}`}
      ref={card}
      data-testid="landing-challenge"
    >
      <div aria-live="polite">{box}</div>
      <div className="lp-duel">
        <div className="mine">
          <span className="label">Your memory, version 1</span>
          <p>Retry failed invoice emails once an hour until they send.</p>
          <span className="tag">Kept</span>
        </div>
        <div className="theirs">
          <span className="label">Offered in its place</span>
          <p>Retry with backoff, five times, then flag the invoice for a person.</p>
          <span className="tag">In force</span>
        </div>
      </div>
      <p className="lp-reasoning">“Hourly retries sent one customer forty copies when their address bounced.” — Asha</p>
      <div className="lp-actions">
        {decision === "waiting" ? (
          <>
            <button
              className="lp-btn go small"
              type="button"
              onClick={() => {
                setDecision("accepted");
                burst();
              }}
            >
              Accept and supersede
            </button>
            <button className="lp-btn plain small" type="button" onClick={() => setDecision("kept")}>
              Keep mine
            </button>
          </>
        ) : (
          <button className="lp-link-button" type="button" onClick={() => setDecision("waiting")}>
            Decide again
          </button>
        )}
      </div>
    </div>
  );
}

/* ---------- Two sessions reaching for one file ---------- */

function CollisionScene() {
  const [ref, seen] = useSeen<HTMLDivElement>(0.4);
  const notice = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tree = ref.current;
    if (!tree) return;
    const run: Run = { stop: false };
    const one = (selector: string) => tree.querySelector<HTMLElement>(selector) as HTMLElement;
    const asha = one(".lp-cursor.asha");
    const ben = one(".lp-cursor.ben");
    const jobs = one('[data-file="jobs"]');
    const point = (cursor: HTMLElement, file: string, dx: number) => {
      cursor.style.transform = `translate(${dx}px, ${one(`[data-file="${file}"]`).offsetTop + 10}px)`;
    };
    const show = (on: boolean) => notice.current?.classList.toggle("show", on);
    point(asha, "api", 120);
    point(ben, "emails", 230);
    if (!seen) return;

    if (reduced()) {
      point(asha, "jobs", 120);
      jobs.classList.add("held");
      show(true);
      return;
    }
    const step = async (ms: number) => {
      await sleep(ms);
      return run.stop;
    };
    async function loop() {
      while (!run.stop) {
        jobs.classList.remove("held", "clash");
        show(false);
        point(asha, "api", 120);
        point(ben, "emails", 230);
        if (await step(1300)) return;
        point(asha, "queue", 150);
        if (await step(1200)) return;
        point(asha, "jobs", 120);
        if (await step(900)) return;
        jobs.classList.add("held");
        if (await step(1100)) return;
        point(ben, "queue", 200);
        if (await step(1000)) return;
        point(ben, "jobs", 210);
        if (await step(900)) return;
        jobs.classList.add("clash");
        show(true);
        if (await step(500)) return;
        jobs.classList.remove("clash");
        if (await step(3800)) return;
      }
    }
    void loop();
    return () => {
      run.stop = true;
    };
  }, [seen, ref]);

  return (
    <div>
      <div className="lp-tree" ref={ref} role="img" aria-label="Asha’s session holds billing/jobs.py when Ben’s reaches for it">
        <div className="file dir">billing/</div>
        {["api", "jobs", "queue", "emails"].map((file) => (
          <div className="file" data-file={file} key={file}>
            {file}.py
            {file === "jobs" && (
              <span className="lock">
                <IconLock size={14} stroke={STROKE} aria-hidden /> Asha
              </span>
            )}
          </div>
        ))}
        <div className="lp-cursor asha">
          <IconPointerFilled size={18} />
          <span>Asha</span>
        </div>
        <div className="lp-cursor ben">
          <IconPointerFilled size={18} />
          <span>Ben</span>
        </div>
      </div>
      <div className="lp-notice" ref={notice}>
        <IconLock size={18} stroke={STROKE} aria-hidden />
        <div>
          <b>Collision.</b> Asha’s session holds <code>billing/jobs.py</code>.
          <div className="opts">
            <span>Wait for it</span>
            <span>Work elsewhere</span>
            <span>Takeover</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- The console, toured ---------- */

const TOUR: { tab: string; title: string; text: string; panel: ReactNode }[] = [
  {
    tab: "Read",
    title: "Read it like documentation",
    text: "Team memory and every project you can reach, folder by folder, set exactly as your agent reads it.",
    panel: (
      <>
        <div className="title">The sandbox gateway drops webhooks over 64 KB</div>
        <div className="status">
          <p>
            <b>In force.</b> Project memory, a gotcha. Pinned.
          </p>
        </div>
        <p>Payloads over 64 KB are dropped without an error. Split large events, or test against the real gateway.</p>
        <p className="when">First written 14 October 2026 by Asha Rao. Version 1 of 1.</p>
      </>
    ),
  },
  {
    tab: "History",
    title: "See what it said, and when",
    text: "Every version, who made it and when. Read a memory as it stood on the day something went wrong.",
    panel: (
      <>
        <div className="title">Release only through the release job</div>
        <ul>
          <li>
            <b>Version 3</b>, in force from 12 September. Ben made releases wait their turn.
          </li>
          <li>
            <b>Version 2</b>, 20 May to 12 September. Asha dropped the staging step.
          </li>
          <li>
            <b>Version 1</b>, 3 March to 20 May. Written by Asha.
          </li>
        </ul>
      </>
    ),
  },
  {
    tab: "Challenges",
    title: "Decide what stands",
    text: "Challenges waiting for you, with the reasoning and what is offered in their place. Pin what every session should hear; retire what’s no longer true.",
    panel: (
      <>
        <div className="title">
          Challenges <span className="chip">2 waiting</span>
        </div>
        <table>
          <tbody>
            <tr>
              <th>Memory</th>
              <th>Raised by</th>
            </tr>
            <tr>
              <td>Retry failed emails hourly</td>
              <td>Asha</td>
            </tr>
            <tr>
              <td>Feature flags live in the config repository</td>
              <td>Chen</td>
            </tr>
          </tbody>
        </table>
      </>
    ),
  },
  {
    tab: "Team and access",
    title: "Run who reaches what",
    text: "An owner, admins and members, a lead for each project, and restricted projects that are invisible to anyone outside their access list. Personal tokens are shown once.",
    panel: (
      <table>
        <tbody>
          <tr>
            <th>Member</th>
            <th>Role</th>
          </tr>
          <tr>
            <td>Olive Owner</td>
            <td>Owner</td>
          </tr>
          <tr>
            <td>Asha Rao</td>
            <td>Admin, lead of billing</td>
          </tr>
          <tr>
            <td>Ben Okafor</td>
            <td>Member</td>
          </tr>
          <tr>
            <td>payroll</td>
            <td>Restricted: 3 on its access list</td>
          </tr>
        </tbody>
      </table>
    ),
  },
  {
    tab: "Audit log",
    title: "Every change has a name",
    text: "Who changed members, roles, access, personal tokens or memory, and when.",
    panel: (
      <table>
        <tbody>
          <tr>
            <th>When</th>
            <th>What</th>
          </tr>
          <tr>
            <td>10:42</td>
            <td>Olive issued Ben a personal token</td>
          </tr>
          <tr>
            <td>10:15</td>
            <td>Asha added Chen to payroll’s access list</td>
          </tr>
          <tr>
            <td>09:58</td>
            <td>Ben retired “Deploys freeze on Fridays”</td>
          </tr>
        </tbody>
      </table>
    ),
  },
];
const TOUR_STEP_MS = 5200;

function ConsoleTour() {
  const [tab, setTab] = useState(0);
  const [touring, setTouring] = useState(true);
  const bars = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    if (!touring || reduced()) return;
    const started = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / TOUR_STEP_MS);
      bars.current[tab]?.style.setProperty("--p", String(progress));
      if (progress < 1) frame = requestAnimationFrame(step);
      else setTab((t) => (t + 1) % TOUR.length);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [tab, touring]);

  const shown = TOUR[tab];
  if (!shown) return null;
  return (
    <>
      <div className="lp-tabs" role="tablist" aria-label="The console">
        {TOUR.map((stop, i) => (
          <button
            key={stop.tab}
            type="button"
            role="tab"
            aria-selected={i === tab}
            onClick={() => {
              setTouring(false);
              setTab(i);
            }}
          >
            {stop.tab}
            {i === tab && (
              <span
                className="bar"
                ref={(el) => {
                  bars.current[i] = el;
                }}
                style={touring ? undefined : ({ "--p": 1 } as React.CSSProperties)}
              />
            )}
          </button>
        ))}
      </div>
      <div className="lp-tour" role="tabpanel">
        <div>
          <h3>{shown.title}</h3>
          <p>{shown.text}</p>
        </div>
        <div className="lp-frame" aria-hidden="true">
          <div className="lp-frame-top">Shared Memory</div>
          <div className="lp-frame-body">
            <div className="lp-frame-side">
              <div>Team memory</div>
              <div className="cur">billing</div>
              <div>deploy</div>
              <div>mobile app</div>
              <div>
                <IconLock size={12} stroke={STROKE} /> payroll
              </div>
            </div>
            <div className="lp-frame-main" key={tab}>
              {shown.panel}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

/* ---------- Pricing ---------- */

function Pricing() {
  const [hosting, setHosting] = useState<Hosting>("hosted");
  const [billing, setBilling] = useState<Billing>("yearly");

  return (
    <section className="lp-sec tinted" id="pricing">
      <div className="lp-wrap">
        <Heading>One price for the whole team.</Heading>
        <p className="lp-intro">
          Pick your team’s size and who runs the server. Every plan has every feature, for every coding agent your
          members use.
        </p>
        <div className="lp-calc">
          <Choice
            className="hosting"
            label="Who runs the server"
            value={hosting}
            options={[
              ["hosted", "Hosted by us"],
              ["self-hosted", "Self-hosted"],
            ]}
            onChange={setHosting}
          />
          {hosting === "hosted" && (
            <Choice
              label="Billing"
              value={billing}
              options={[
                ["monthly", "Monthly"],
                [
                  "yearly",
                  <>
                    Yearly <small>save over 20%</small>
                  </>,
                ],
              ]}
              onChange={setBilling}
            />
          )}
        </div>
        <p className="lp-hosting-line">
          {hosting === "hosted"
            ? `We run a server for your team alone, back it up and keep it current. Try it for ${TRIAL_DAYS} days before you pay.`
            : "Run it on a server you control, with Docker, under a yearly license. Search runs on a model inside the server, so memory never leaves it."}
        </p>
        <div className="lp-plans">
          {PLAN_SIZES.map((size) => (
            <Plan key={size} size={size} hosting={hosting} billing={billing} />
          ))}
        </div>
        <div className="lp-every">
          <h3>Every plan includes</h3>
          <ul>
            <li>All seven coding agents</li>
            <li>Briefing and recall</li>
            <li>Promotion with contradiction checks</li>
            <li>Project, team and personal levels</li>
            <li>Every version, with names</li>
            <li>Challenges</li>
            <li>Sessions, locks and collisions</li>
            <li>The console</li>
            <li>Owner, admins and project leads</li>
            <li>Restricted projects</li>
            <li>Audit log</li>
            <li>GitHub sign-in</li>
          </ul>
        </div>
        <p className="lp-more">
          More than fifteen members? <Link to="/coming-soon?for=contact">Talk to us.</Link>
        </p>
      </div>
    </section>
  );
}

function Plan({ size, hosting, billing }: { size: PlanSize; hosting: Hosting; billing: Billing }) {
  const price = planPrice(hosting, billing, size);
  const amount = useCounted(price.amount);
  return (
    <article className="lp-plan" data-testid={`plan-${size}`}>
      <h3>Up to {size} members</h3>
      <div className="lp-seats" aria-hidden="true">
        {Array.from({ length: 15 }, (_, i) => (
          <i key={i} className={i < size ? "on" : undefined} style={{ "--i": i } as React.CSSProperties} />
        ))}
      </div>
      <div className="lp-price" aria-label={`${money(price.amount)} ${price.per}`}>
        <span className="cur" aria-hidden="true">
          $
        </span>
        <span className="amount" aria-hidden="true">
          {amount.toLocaleString("en-US")}
        </span>
        <span className="per" aria-hidden="true">
          {price.per}
        </span>
      </div>
      <p className="lp-terms">{price.terms}</p>
      {/* Checkout and licensing don't exist yet (#354, #355), so both actions say what is coming. */}
      <Link className="lp-btn go small" to={`/coming-soon?for=${hosting === "hosted" ? "trial" : "license"}`}>
        {price.action} <IconArrowRight size={16} stroke={2} />
      </Link>
    </article>
  );
}

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  value: T;
  options: [T, ReactNode][];
  onChange: (value: T) => void;
  className?: string;
}) {
  const second = options[1]?.[0] === value;
  return (
    <div
      className={["lp-seg", className, second ? "second" : null].filter(Boolean).join(" ")}
      role="radiogroup"
      aria-label={label}
    >
      {options.map(([option, text]) => (
        <button key={option} type="button" role="radio" aria-checked={option === value} onClick={() => onChange(option)}>
          {text}
        </button>
      ))}
      <span className="thumb" aria-hidden="true" />
    </div>
  );
}
