# The console signs in with GitHub, and Claude sessions keep personal tokens

Members sign in to the console with their GitHub account, which an admin links to their member record; Claude Code sessions still prove who they are with a personal token (ADR-0005). The team already lives on GitHub, and the plugin marketplace is a GitHub repository, so no new accounts or passwords are needed.

## Considered Options

- **Pasting the personal token into the browser**: rejected because it spreads the token that Claude sessions depend on, into browsers and their storage, with no second factor.
- **Google sign-in**: workable, but the team's work identity is GitHub, and GitHub is already a dependency.

## Consequences

- A member has two credentials: a personal token for Claude Code and a GitHub account for the console. The token never has to go into a browser.
- Matching is by the GitHub account's numeric id once a member has signed in, so a renamed GitHub account keeps working.
- A deployment without a GitHub app configured runs as before, with the console's sign-in disabled.
