#!/usr/bin/env bash
# Everything that has to be true before `docker compose up -d --build`, checked in a couple of seconds.
#
# The build takes several minutes and downloads a few hundred megabytes, so the things that make it fail are
# worth knowing first. Two of them fail quietly rather than loudly: a missing backup key becomes a *directory*
# the moment Compose mounts it, and a host that is too small gets its console build killed by the kernel with
# no message that says so.
#
# Run it from this folder: ./preflight.sh

set -u

RED=$'\033[31m'; YELLOW=$'\033[33m'; GREEN=$'\033[32m'; DIM=$'\033[2m'; RESET=$'\033[0m'
problems=0
warnings=0

bad()  { printf '%s✗%s %s\n' "$RED" "$RESET" "$1"; problems=$((problems + 1)); }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$1"; warnings=$((warnings + 1)); }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
why()  { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }

cd "$(dirname "$0")" || exit 1

# --- Docker ---

if ! command -v docker >/dev/null 2>&1; then
    bad "Docker isn't installed."
    why "The whole stack is containers; nothing below can be checked without it."
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    bad "Docker Compose v2 isn't available (\`docker compose version\` failed)."
    why "This stack uses the v2 syntax; the old docker-compose binary won't read it."
    exit 1
fi
ok "Docker and Compose v2 are here."

# --- .env and the three settings with no default ---

if [ ! -f .env ]; then
    bad "No .env beside this script."
    why "Copy .env.example to .env and fill it in; see docs/deployment.md."
    exit 1
fi

# shellcheck disable=SC1091
set -a; . ./.env; set +a

for name in SHARED_MEMORY_DOMAIN POSTGRES_PASSWORD BACKUP_REMOTE; do
    if [ -z "${!name:-}" ]; then
        bad "$name is empty in .env."
        why "Compose refuses to start without it, after you have waited for the build."
    fi
done
[ "$problems" -eq 0 ] && ok ".env has the settings that have no default."

# --- The backup key, before Compose turns it into a directory ---

KEY="${BACKUP_SSH_KEY:-./backup_key}"
if [ -d "$KEY" ]; then
    bad "$KEY is a directory."
    why "Compose creates one when the key is missing at mount time. Remove it, then make the key."
elif [ ! -f "$KEY" ]; then
    bad "$KEY doesn't exist."
    why "Make it first, or Compose mounts a directory in its place and every backup fails at ${BACKUP_TIME:-02:00}:"
    why "  ssh-keygen -t ed25519 -N \"\" -C shared-memory-backup -f backup_key"
elif [ ! -s "$KEY" ]; then
    bad "$KEY is empty."
else
    ok "The backup key is a file with something in it."
fi

# --- Ports, unless this stack already holds them ---

listening() {
    if command -v ss >/dev/null 2>&1; then ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN
    elif command -v netstat >/dev/null 2>&1; then netstat -ltn 2>/dev/null | grep -qE "[:.]$1 .*LISTEN"
    else return 1
    fi
}
ours=$(docker compose ps --services --filter status=running 2>/dev/null | grep -cx caddy || true)
for port in 80 443; do
    if listening "$port" && [ "$ours" -eq 0 ]; then
        bad "Something is already listening on port $port."
        why "Caddy binds both to answer the certificate challenge and to serve the console."
    fi
done
[ "$ours" -gt 0 ] && ok "This stack's Caddy already holds 80 and 443."

# --- DNS, which the certificate depends on ---

resolved=""
if command -v getent >/dev/null 2>&1; then
    resolved=$(getent ahostsv4 "${SHARED_MEMORY_DOMAIN:-}" 2>/dev/null | awk 'NR==1 {print $1}')
fi
if [ -z "$resolved" ]; then
    bad "${SHARED_MEMORY_DOMAIN:-the domain} doesn't resolve."
    why "Caddy asks Let's Encrypt over HTTP on port 80, which needs the name pointing here first."
    why "A new record can take a few minutes; the certificate attempt is rate limited, so wait rather than retry."
else
    mine=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)
    if [ -n "$mine" ] && [ "$mine" != "$resolved" ]; then
        warn "$SHARED_MEMORY_DOMAIN resolves to $resolved, but this host looks like $mine."
        why "If the record was just changed this is propagation. If not, the certificate will fail."
    else
        ok "$SHARED_MEMORY_DOMAIN resolves to $resolved."
    fi
fi

# --- Room to build ---

if [ -r /proc/meminfo ]; then
    kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
    swap=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
    mb=$(( (kb + swap) / 1024 ))
    if [ "$mb" -lt 1900 ]; then
        bad "Only ${mb}MB of memory and swap together."
        why "The build runs a Vite build for the console and installs onnxruntime for the server."
        why "Below about 2GB the console build is killed by the kernel, and the error won't say why."
    elif [ "$mb" -lt 3800 ]; then
        warn "${mb}MB of memory and swap together."
        why "It usually builds, but 4GB is the comfortable floor. Add swap if the build dies:"
        why "  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
    else
        ok "${mb}MB of memory and swap: enough to build."
    fi
fi

free_gb=$(df -P . | awk 'NR==2 {print int($4 / 1048576)}')
if [ "${free_gb:-99}" -lt 10 ]; then
    warn "${free_gb}GB free on this filesystem."
    why "Images, Postgres, the memory repository and the search model want room; 25GB is comfortable."
else
    ok "${free_gb}GB free."
fi

# --- The backup's way out ---

if ! timeout 5 bash -c 'cat < /dev/null > /dev/tcp/github.com/22' 2>/dev/null; then
    warn "Can't reach github.com on port 22 from here."
    why "The nightly backup pushes over SSH. Check the firewall's outbound rules before 02:00 does it for you."
fi

# --- What to do about it ---

echo
if [ "$problems" -gt 0 ]; then
    printf '%s%d thing(s) to fix before building.%s\n' "$RED" "$problems" "$RESET"
    exit 1
fi
if [ "$warnings" -gt 0 ]; then
    printf '%s%d warning(s). Read them, then:%s docker compose up -d --build\n' "$YELLOW" "$warnings" "$RESET"
    exit 0
fi
printf '%sReady.%s docker compose up -d --build\n' "$GREEN" "$RESET"
