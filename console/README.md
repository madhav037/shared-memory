# Shared Memory console

The team's web app: members browse memory, admins run the team. It is a React app in TypeScript, built to static files, talking to the JSON API in the Python server on the same origin (ADR-0008). The spec is issue #22.

## Working on it

```bash
npm install
npm run dev        # http://127.0.0.1:5173, /api proxied to http://127.0.0.1:8000
```

Point it at another server with `SHARED_MEMORY_SERVER`. Run the server itself with `docker compose up -d db server` from the repository root.

## Checks

```bash
npm run typecheck  # types
npm run build      # types, then static files into dist/
npm run api:check  # the committed API types still match openapi.json
npm run e2e        # browser journeys: starts a server on a fresh database and the built console
```

The first `npm run e2e` needs browsers: `npm run e2e:install`.

## The API's types

`openapi.json` is the server's own description of its API, and `src/api/schema.d.ts` is generated from it. After changing the API:

```bash
uv run shared-memory openapi > console/openapi.json   # from the repository root
npm run api:types
```

A test in `tests/` fails if `openapi.json` falls behind the server, and `npm run api:check` fails if the types fall behind `openapi.json`.

## Signing in while you work on it

Sign-in needs a GitHub app. For local work, the browser journeys' server (`tests/console_e2e_server.py`) already runs with a fake GitHub and a seeded team, so `npm run e2e` needs nothing set up. To sign in by hand against a real GitHub app, run the server with `SHARED_MEMORY_GITHUB_CLIENT_ID`, `SHARED_MEMORY_GITHUB_CLIENT_SECRET` and `SHARED_MEMORY_CONSOLE_URL`, and register `<console URL>/api/sign-in/github/callback` as the app's callback.
