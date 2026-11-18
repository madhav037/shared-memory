# Hosted servers share hosts, not processes

Each team's hosted server is its own stack: its own server process, with one worker, and its own database. Several stacks share one host, and that host's Postgres instance holds a database and a role for each team. One idle team measured about 710 MiB with two workers, so packing stacks onto shared hosts is what makes the plans' prices profitable. Running one process per team keeps a team's memory unreachable from another team's code.

## Considered options

- **A VM per team** gives the strongest isolation, but every team then costs a whole VM. It stays open as a paid add-on.
- **One multi-team service** packs teams the most densely. It also turns every query into a cross-team leak risk and rewrites a server built for one team.
- **A Postgres per team** costs about 70 MiB more per team and gives no extra separation once each team has its own database and role.
- **One embedding service shared by a host** would shrink each team's process further, but every team's memory text would pass through a shared process. Instead, each team keeps the model in its own single worker.

## Consequences

- One team's stack restarts, upgrades and restores without touching the others on the same host.
- When every host is past about 75% of its RAM, the platform adds a host through Hetzner's API, up to a ceiling set in the vendor console.
