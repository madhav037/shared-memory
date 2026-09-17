# The console is a React app on a JSON API, served from the same domain

The console is a React single-page app written in TypeScript and built to static files, talking to a JSON API in the existing Python server. Caddy serves the static files and proxies the API, the MCP transport and the hook endpoints, so there is one domain, one certificate and one deployment.

## Considered Options

- **Pages rendered by the Python server**: fewer moving parts and no second language, but the console's browsing, history and access-control screens are interactive enough to be worth a real frontend.

## Consequences

- There is a second toolchain (Node) in the build, and the deployment stack gains a build step for the console's files.
- The API's shapes are published as an OpenAPI document and the console's TypeScript types are generated from it, so the two can't drift apart without the build failing.
- Requests stay same-origin, so the session cookie needs no cross-origin sharing.
