# Only a department lead promotes into department memory

Any member may promote into project or company memory, and a challenge is the safety net. Department memory is different: it reaches every project in the department, and the members working in one of them rarely see the others. So only a department lead promotes into department memory. Another member's promotion there becomes a challenge to the department's leads, and the memory stays that member's personal memory until it is decided. Confirmed by the repo's human on 2026-11-21 (#600).

## Considered options

- **Any member promotes, as at the other levels.** Rejected: one project's habit would land on every project in the department with nobody from those projects asked.
- **A separate approval queue.** Rejected: a challenge already carries Reasoning, reaches the decider's briefing and has a console screen, as a foundation challenge does (ADR-0019).

## Consequences

- A department lead's own promotion still runs the contradiction check (ADR-0004), and one that contradicts company memory is a level contradiction they settle at once.
- Accepting the challenge promotes the memory in its author's name. Deciding it is governing; the console may do it (ADR-0009).
- A department with no lead left is decided by the company's admins.
