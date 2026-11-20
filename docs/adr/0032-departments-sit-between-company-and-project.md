# Departments sit between company and project

A large company has rules that many of its projects share but the whole company doesn't: a platform group's ways of working, a delivery unit's review habits. A company may now group projects into **departments**, one level deep, each with **department memory** and one or more **department leads**. A project sits in at most one department; a project in none reads company memory only, so existing servers change nothing. Levels complement each other: company memory is policy, department memory is ways of working, project memory is the product. Architecture and decisions stay in a project's foundations (ADR-0019); departments have no foundations. Confirmed by the repo's human on 2026-11-21 (#600).

When a memory contradicts one at a broader level, it is a **level contradiction**, and the narrower level's lead settles it: a project lead for project memory, a department lead for department memory. It is raised in both directions: when a narrower memory is promoted against a broader one, and when a broader memory is promoted against memory already below it. The lead is told in their briefing and the console, and either makes theirs follow the broader memory or keeps it as an **exception**. Until they decide, the narrower memory still holds for its own project or department, marked as waiting.

## Considered options

- **Nested departments.** Rejected: precedence and access across arbitrary depth is hard to explain to a member and hard for a briefing to stay short; one level covers every case the personas described.
- **The broader memory wins at once.** Rejected: a company rule added later would silently overturn a project's working practice that nobody there was asked about.
- **The member promoting decides, as for an exception to team memory before.** Rejected: an exception speaks for a whole project or department, so its lead keeps it.
- **A separate server per department.** Rejected: company memory would have to be copied to each, and admins would run several servers for one company. A server per client stays the answer only for services firms, whose client boundary is contractual (#597 carries their practices across).

## Consequences

- A department is open to the whole company unless restricted to an access list. A restricted department's memory and projects are invisible outside it, and a project inside it can be restricted further, never opened wider (extending ADR-0006).
- A briefing carries pins from company, department and project memory, and recall searches all three. Keeping the briefing short across more levels is the spec's to solve.
- The contradiction check still runs in the promoting session's coding agent (ADR-0004), which is now shown similar memories at the levels below as well as above.
- A challenge against department memory may be decided by its author, a department lead or an admin (extending ADR-0017).
- Department leads manage their department's projects, access and keepers; admins can do the same. Department leads see their projects' aggregates, never figures for one member.
- Keeping an exception, or retiring the narrower memory to follow the broader one, is governing and may be done from the console. Rewriting the narrower memory to follow it is writing, so that happens in a session (ADR-0009).
