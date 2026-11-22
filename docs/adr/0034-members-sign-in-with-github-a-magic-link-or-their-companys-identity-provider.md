# Members sign in with GitHub, a magic link or their company's identity provider

ADR-0007 made GitHub the console's only sign-in, which shuts out companies whose people don't all have GitHub accounts. A member now has one or more sign-in methods, all leading to the same member through a verified email: GitHub, a magic link, and on a self-hosted server the company's own identity provider over OIDC, on every plan. The platform runs Logto, an MPL-2.0 identity server, as its one sign-in service; hosted servers keep the handed-over sign-in and never talk to Logto themselves. Personal tokens for coding agents are unchanged (ADR-0005).

## Considered Options

- **Clerk**: rejected. It is closed source and hosted by Clerk, so every self-hosted server would depend on Clerk being up and on the vendor's Clerk account.
- **Keycloak**: rejected. It needs well over 500 MiB of RAM and is clumsy to theme.
- **Zitadel, Ory Kratos, Authentik**: workable. Logto won because it stores its data in Postgres, which the platform already runs, ships magic links, GitHub and multi-factor sign-in ready-made, and has the simplest sign-in screens to theme. Kratos would have made us build every screen ourselves.
- **Writing every sign-in method into our own code**: rejected for the platform, where Logto also covers the vendor console's second factor and the GitLab or Azure sign-in to come. Self-hosted servers do carry their own magic links and OIDC, so they never depend on the vendor.

## Consequences

- A member is no longer identified only by a GitHub account. Admins invite by email or GitHub login, and only invited people may join.
- Existing members' emails come from GitHub at their next sign-in, and members can change and re-confirm their email in their settings.
- Logto runs only on the platform, so hosted servers use no extra RAM. Its admin screen is reachable only from the platform machine itself.
- The vendor console accepts any sign-in method, but only for allow-listed accounts, and every one of them must pass a second factor.
