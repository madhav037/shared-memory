# Builds the console and serves it, with Caddy in front of the server (ADR-0008).
# Build context is the repository root, so this image can build console/ from source.
FROM node:22-alpine AS build

WORKDIR /console
COPY console/package.json console/package-lock.json ./
RUN npm ci
COPY console/ ./
RUN npm run build

FROM caddy:2

COPY --from=build /console/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
