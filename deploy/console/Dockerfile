# Builds the console and serves it, with Caddy in front of the server (ADR-0008).
# Build context is the repository root, so this image can build console/ from source.
FROM node:22-alpine AS build

WORKDIR /console
COPY console/package.json console/package-lock.json ./
RUN npm ci
COPY console/ ./
RUN npm run build

# Caddy with the rate-limit module, which the stock image lacks (the edge's coarse limit, see the Caddyfile).
FROM caddy:2-builder@sha256:3db11aead97f1fdff9c563d0dd8e7fba2e4c7031bef40f3e44fd1982f3e8366b AS caddy
# Pinned to a commit: an unpinned module is whatever its master is on build day, and the live site is built from this.
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@5625512f24f6f59d6f64fb3aafe5eecff0b286db

# Pinned, like the builder, so its layers stay the ones the server has; Dependabot moves the pins.
FROM caddy:2@sha256:ce773ec7a742ce15ee6bf2bb5f65882b9e2a4487b10733e6f1484f86e6b5d8bc

COPY --from=caddy /usr/bin/caddy /usr/bin/caddy

COPY --from=build /console/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
