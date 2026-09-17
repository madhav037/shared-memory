# Admins, project leads and restricted projects

v1 had one owner, and every member could reach every project. That made the owner a bottleneck and left no way to keep a sensitive project from the whole team. A team now has admins who run it alongside the owner, and each project has project leads who look after it; a project is open to the team unless a lead or an admin restricts it to an access list.

## Considered Options

- **Admins only, every project open to the team**: rejected because a customer's project or an acquisition can't be kept from everyone.
- **An access list on every project**: rejected because a new repository's memory would stop working until someone granted access, which punishes the common case to protect the rare one.

## Consequences

- Reach is checked when a call is authenticated, so it covers every memory tool and both hooks at once, and a member who loses access loses it on their next call.
- Team memory stays readable by the whole team, so restricting a project never splits the team's shared conventions.
- Admins and the owner can reach every project, including restricted ones, because they have to be able to govern and repair them.
