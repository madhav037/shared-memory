# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary: the team's developers** (members, in `CONTEXT.md`'s words), who each work in Claude Code with the Shared Memory plugin. They open the console to read memory and its folder structure, confirmed by the user on 2026-09-19.
- **Also: the owner, admins and project leads**, who run the team from the same console: members, roles, projects, access lists and the audit log.
- One team of up to about 15 members (`docs/design.md` §2).

## Product Purpose

Shared Memory is a memory that every member's Claude sessions read and write, so what one member's Claude learns reaches every other member's Claude and the team's ways of working stay consistent.

The console is where people see that memory for themselves: read it like documentation, check exactly what Claude was told, follow how a memory changed, decide disputes about it, and run who can reach what. Success is a member finding and trusting the right memory in under a minute.

## Positioning

- Memory is plain Markdown files with a small header, on a server, with every change in a git history (ADR-0002, ADR-0003). What the console shows is exactly what every Claude reads, word for word.
- Memory has **levels** with a fixed order of weight: project memory over team memory over personal memory. Whether something is accepted by the team or one member's note is never ambiguous.
- The console **governs memory but never writes it** (ADR-0009): writing, editing and promoting stay in a member's own Claude, where the contradiction check runs (ADR-0004).

## Operating Context

Confirmed by the user: people use it for several jobs.

- **Reading memory like docs**: browsing the folder structure of team memory and each project, reading a memory in full.
- **Verifying things while debugging**: checking what memory said, and when, when a Claude session did something surprising; comparing versions of a memory.
- **Deciding challenges** waiting for them, and seeing how their own ended.
- **Running the team**: members, admins, projects and their leads, restricted projects and access lists, personal tokens, the audit log.

Visits sit between Claude Code sessions, mostly at a desk; the spec also asks for phone use (story 75 of #22).

## Capabilities and Constraints

- Sign-in is GitHub only (ADR-0007). A member's personal token for Claude Code is shown once, when issued, and never again.
- Roles: owner, admin, member; plus project leads per project. A project is open to the team unless restricted to its access list (ADR-0006); a restricted project must be invisible to anyone outside it.
- Memory types: convention, decision, architecture, gotcha. Statuses: active, superseded, retired. Memory can be grouped into topics (folders with an index).
- The console can pin and unpin, decide challenges and retire; it cannot write, edit or promote memory. That is a deliberate no, not a missing feature.
- Stack: a React + TypeScript single-page app built with Vite (ADR-0008), on the server's JSON API, whose types are generated from the API description. Served from the same domain as the server by Caddy.
- Terminology is fixed by `CONTEXT.md`; the console uses those words (memory, not note or doc; member, not user; challenge, pin, retire, supersede, promote).

## Brand Commitments

- The product is called **Shared Memory**. There is no logo, mark or brand palette yet. *(Inferred: nothing in the repository defines one.)*
- Voice: plain, direct sentences that say what happened and what to do next, the way the server's refusals already read.

## Evidence on Hand

- No customers, testimonials, metrics or case studies exist; the product is in its first trial with the author's own team. Nothing of that kind may be invented.
- Real content: the demo team seeded for development, and the memory examples in `docs/design.md`.

## Product Principles

1. **Show memory exactly as Claude reads it.** Never paraphrase, summarise away or restyle the words; the page is the source.
2. **Weight is always visible.** Every memory shows its level and status where it is shown, so a member can't mistake one person's note, or a retired memory, for a team convention.
3. **Reach follows access.** Nothing about a restricted project appears to someone outside it, anywhere.
4. **Every change has a name on it.** Who changed what, and when, is one click away: in a memory's history and in the audit log.
5. **Govern, don't author.** The console decides and curates; knowledge is written where it is learned, in a Claude session.

## Accessibility & Inclusion

- Usable with a keyboard and a screen reader (story 76 of #22), and on a phone screen (story 75).
- *(Inferred)* Target WCAG 2.2 AA contrast and focus visibility in both light and dark themes.
