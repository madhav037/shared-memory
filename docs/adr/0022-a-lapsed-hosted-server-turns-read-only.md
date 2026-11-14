# A lapsed hosted server turns read-only; a self-hosted one never does

A self-hosted server with no license key, or a lapsed one, only shows a banner (#416). The FSL license protects the code, and nothing technical could stop someone deleting the check anyway. A hosted server is different: we pay for the RAM it uses. So when its license key lapses, it turns read-only. Members can still read and export memory, and their coding agents keep reading it, but nothing new is saved. Fourteen days later the server is stopped, and its data is deleted thirty days after that. Paying at any point restores it.

## Considered options

- **Stopping the server the day it lapses** frees RAM sooner, but coding agents lose memory with no warning.
- **A banner only, as on self-hosted servers** keeps unpaid servers running at our cost indefinitely.

## Consequences

- The rule "memory never depends on the license key" now holds only for self-hosted servers. The server needs to know which kind it is, and a hosted server's key says so.
- Hooks still never block a coding agent. A read-only server answers a save with a plain refusal, the way the member cap refuses a member.
