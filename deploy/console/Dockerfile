# Builds the console and serves it, with Caddy in front of the server (ADR-0008).
# Build context is the repository root, so this image can build console/ from source.
FROM node:26-alpine AS build

WORKDIR /console
COPY console/package.json console/package-lock.json ./
RUN npm ci
COPY console/ ./
RUN npm run build

# Caddy with the rate-limit module, which the stock image lacks (the edge's coarse limit, see the Caddyfile).
FROM caddy:2-builder@sha256:cda07fe9d82728c7ac44d844306d435e98131423dc7b114f05a8a8ecfff94707 AS caddy
# Pinned to a commit: an unpinned module is whatever its master is on build day, and the live site is built from this.
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@5625512f24f6f59d6f64fb3aafe5eecff0b286db

# Pinned, like the builder, so its layers stay the ones the server has; Dependabot moves the pins.
FROM caddy:2@sha256:4851e54a46b206517c574821bb5cc67f170d2156041e9fbc4c9193b45e84a75b

COPY --from=caddy /usr/bin/caddy /usr/bin/caddy

COPY --from=build /console/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
