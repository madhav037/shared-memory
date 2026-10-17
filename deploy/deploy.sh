#!/usr/bin/env bash
# Puts a release of Shared Memory on this host. GitHub Actions runs it over SSH (.github/workflows/deploy.yml).
#
#   check                   check the host and print the running release; changes nothing
#   deploy <commit>         read the release's images from stdin (docker save, gzipped), back up, switch to them, and
#                           put the running release back if the new one isn't healthy
#   deploy <commit> drill   the same, but treat the new release as unhealthy, to rehearse putting one back. Only for
#                           the commit already running, so the database is never switched back under a newer server.
#
# GitHub's key may run nothing but this script (`restrict,command=` in ~/.ssh/authorized_keys), so this file is the
# whole of what GitHub can do here. It is installed by hand, outside the checkout, so a change to it reaches the host
# only when someone installs it again (docs/deployment.md, "Deploying from GitHub"):
#
#   install -m 755 deploy/deploy.sh ~/.local/bin/shared-memory-deploy
#
# It runs as the stack's own user under rootless Docker and never asks for root. The host's web server, its sites and
# its certificates are looked at (is nginx running, do 80 and 443 answer as they did) and never touched.

REPO="${SHARED_MEMORY_REPO:-$HOME/shared-memory}"
STATE="${SHARED_MEMORY_DEPLOY_STATE:-$HOME/.local/state/shared-memory-deploy}"
HEALTH_SECONDS="${SHARED_MEMORY_HEALTH_SECONDS:-180}"
HEALTH_INTERVAL="${SHARED_MEMORY_HEALTH_INTERVAL:-5}"
MIN_FREE_GB="${SHARED_MEMORY_DEPLOY_MIN_FREE_GB:-6}"
MIN_AVAILABLE_MB="${SHARED_MEMORY_DEPLOY_MIN_AVAILABLE_MB:-1024}"
IMAGES=(shared-memory-server shared-memory-caddy shared-memory-backup)
SERVICES="backup caddy db server"

log()  { echo "$(date -u +%H:%M:%S) $*"; }
fail() { echo "$(date -u +%H:%M:%S) ✗ $*" >&2; exit 1; }
usage() { fail "usage: check | deploy <commit> [drill]"; }

compose() { (cd "$REPO/deploy" && docker compose "$@"); }
listening() { ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN; }
answers() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 -k "$@" || true; }

# What the host's own web server answers. A deploy must leave it as it found it.
web_server() {
    systemctl is-active --quiet nginx || fail "The host's nginx isn't running. Nothing deploys onto a host in trouble."
    { listening 80 && listening 443; } || fail "Nothing listens on port 80 or 443, which the host's nginx holds."
    echo "http $(answers http://127.0.0.1/), https $(answers https://127.0.0.1/)"
}

# Room to load a release without crowding the host's other work.
room() {
    docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless \
        || fail "Docker isn't the rootless daemon. This script runs only under rootless Docker."
    local free_gb available_mb
    free_gb=$(df -P "$HOME" | awk 'NR==2 {print int($4 / 1048576)}')
    [ "$free_gb" -ge "$MIN_FREE_GB" ] || fail "Only ${free_gb}GB free; a release needs ${MIN_FREE_GB}GB to load."
    available_mb=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)
    [ "$available_mb" -ge "$MIN_AVAILABLE_MB" ] \
        || fail "Only ${available_mb}MB of memory available; a release needs ${MIN_AVAILABLE_MB}MB."
}

# Healthy is the whole way in, through the host's nginx: a hook answers, the console loads, and all four services run.
healthy() {
    local domain deadline running
    domain=$(sed -n 's/^SHARED_MEMORY_DOMAIN=//p' "$REPO/deploy/.env" | tail -n 1)
    deadline=$((SECONDS + HEALTH_SECONDS))
    while :; do
        if [ "$(answers -X POST "https://$domain/hooks/session-start" -d '{}')" = 200 ] \
            && [ "$(answers "https://$domain/")" = 200 ]; then
            running=$(compose ps --services --status running | sort | xargs)
            [ "$running" = "$SERVICES" ] && return 0
        fi
        [ "$SECONDS" -lt "$deadline" ] || return 1
        sleep "$HEALTH_INTERVAL"
    done
}

# Runs the images tagged $1 with the deploy files of commit $2. Called as a condition, where `set -e` doesn't hold, so
# every step says itself whether it failed.
switch_to() {
    git -C "$REPO" checkout -q --detach "$2" || return 1
    local image
    for image in "${IMAGES[@]}"; do docker tag "$image:$1" "$image:latest" || return 1; done
    compose up -d --no-build --remove-orphans || return 1
}

check() {
    local answered
    answered=$(web_server)
    log "The host's web server answers: $answered"
    room
    log "Running $(git -C "$REPO" rev-parse HEAD)"
    compose ps --format '{{.Service}} {{.Status}}'
}

deploy() {
    local commit=$1 drill=${2:-} previous before after image
    [[ $commit =~ ^[0-9a-f]{40}$ ]] || fail "Not a full commit hash: $commit"
    [ -z "$drill" ] || [ "$drill" = drill ] || usage

    exec 9>"$STATE/lock"
    flock -n 9 || fail "Another deploy is running."

    git -C "$REPO" fetch -q origin main
    git -C "$REPO" merge-base --is-ancestor "$commit" origin/main 2>/dev/null || fail "$commit isn't on main."
    previous=$(git -C "$REPO" rev-parse HEAD)
    [ -z "$drill" ] || [ "$commit" = "$previous" ] || fail "A drill redeploys the running release, $previous."

    before=$(web_server)
    room
    log "Running $previous, deploying $commit. The host's web server answers: $before"

    log "Loading the images"
    gunzip | docker load -q >/dev/null || fail "The images didn't load. Nothing was switched."
    for image in "${IMAGES[@]}"; do
        docker image inspect "$image:$commit" >/dev/null 2>&1 || fail "The upload had no $image:$commit."
    done

    log "Backing up before switching"
    compose exec -T backup backup now || fail "The backup failed, so nothing was switched."

    for image in "${IMAGES[@]}"; do docker tag "$image:latest" "$image:previous"; done
    log "Switching to $commit"
    # A release that fails to start counts as unhealthy, so it too is replaced by the one it replaced.
    if switch_to "$commit" "$commit" && [ -z "$drill" ] && healthy; then
        log "$commit is healthy"
    else
        if [ -n "$drill" ]; then log "Drill: treating $commit as unhealthy"; else log "$commit isn't healthy"; fi
        log "Putting $previous back"
        { switch_to previous "$previous" && healthy; } \
            || fail "$previous isn't healthy either. Look now: docker compose ps, docker compose logs."
        [ -n "$drill" ] || fail "$commit wasn't healthy, so $previous runs again."
        log "Drill done: $previous was put back and is healthy"
    fi

    after=$(web_server)
    [ "$after" = "$before" ] || fail "The host's web server answered $before before the deploy and $after after it."

    # Keep the running release and the one before it; older releases' images go.
    for image in "${IMAGES[@]}"; do
        docker images "$image" --format '{{.Tag}}' | grep -vxE "latest|previous" \
            | while read -r tag; do docker image rm -f "$image:$tag" >/dev/null; done
    done
    docker image prune -f >/dev/null
    log "Done. Running $(git -C "$REPO" rev-parse HEAD)"
}

main() {
    set -euo pipefail
    export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
    mkdir -p "$STATE"
    # Over SSH, the forced command's words arrive in SSH_ORIGINAL_COMMAND, split here and never run as a command.
    local args
    if [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then read -r -a args <<< "$SSH_ORIGINAL_COMMAND"; else args=("$@"); fi
    case "${args[0]:-}" in
        check)  [ "${#args[@]}" -eq 1 ] || usage; check ;;
        deploy) [ "${#args[@]}" -ge 2 ] && [ "${#args[@]}" -le 3 ] || usage; deploy "${args[1]}" "${args[2]:-}" ;;
        *) usage ;;
    esac
}

main "$@"
