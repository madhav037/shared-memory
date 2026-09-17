#!/usr/bin/env bash
# Backs up Shared Memory to a private git repository, and restores from it.
#
#   backup schedule   run a backup every night at BACKUP_TIME (the container's default)
#   backup now        run one backup now
#   backup restore    restore the latest backup into an empty memory folder and database
#   backup health     exit 1 if no backup has succeeded for more than a day
#
# The backup repository holds the memory folder's git history on branch main, and a database dump on branch
# database (one commit per night). The dump leaves out the search index: `shared-memory reindex` rebuilds it.
set -euo pipefail

MEMORY=/data/memory
DATABASE_WORK=/backups/database
LAST_SUCCESS=/backups/last-success
STARTED=/tmp/started
KEY=/run/secrets/backup_key

log() { echo "$(date -Is) $*"; }

use_git() {
    git config --global --add safe.directory '*'
    git config --global user.name "Shared Memory backup"
    git config --global user.email "backup@shared-memory.invalid"
    if [ -f "$KEY" ] && [ -s "$KEY" ]; then
        # ssh refuses a key readable by others, which a mounted file often is.
        install -m 600 "$KEY" /tmp/backup_key
        export GIT_SSH_COMMAND="ssh -i /tmp/backup_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/backups/known_hosts"
    fi
}

backup_now() {
    use_git
    log "Backup started"
    if [ ! -d "$DATABASE_WORK/.git" ]; then
        git init -q -b database "$DATABASE_WORK"
        # Continue the remote's history, for example on a host restored from this backup.
        if git ls-remote --exit-code --heads "$BACKUP_REMOTE" database >/dev/null; then
            git -C "$DATABASE_WORK" fetch -q "$BACKUP_REMOTE" database
            git -C "$DATABASE_WORK" reset -q FETCH_HEAD
        fi
    fi
    # Dump the database before pushing memory, so every memory the dump refers to is already in the push.
    pg_dump --clean --if-exists --no-owner --exclude-table-data=sections -f "$DATABASE_WORK/shared_memory.sql"
    git -C "$DATABASE_WORK" add shared_memory.sql
    if ! git -C "$DATABASE_WORK" diff --cached --quiet; then
        git -C "$DATABASE_WORK" commit -q -m "Database backup $(date -Is)"
    fi
    git -C "$DATABASE_WORK" push -q "$BACKUP_REMOTE" HEAD:database
    if [ -d "$MEMORY/.git" ]; then
        git -C "$MEMORY" push -q "$BACKUP_REMOTE" main
    else
        log "The memory folder has no history yet: nothing to push"
    fi
    touch "$LAST_SUCCESS"
    log "Backup finished"
}

schedule() {
    touch "$STARTED"
    log "Backing up every night at $BACKUP_TIME ($TZ) to $BACKUP_REMOTE"
    while true; do
        now=$(date +%s)
        next=$(date -d "today $BACKUP_TIME" +%s)
        if [ "$next" -le "$now" ]; then
            next=$(date -d "tomorrow $BACKUP_TIME" +%s)
        fi
        sleep $((next - now))
        # A separate process, so a failing step stops that backup (set -e is ignored on the left of ||).
        "$0" now || log "Backup FAILED"
    done
}

health() {
    if [ -n "$(find "$LAST_SUCCESS" -mmin -1560 2>/dev/null)" ]; then
        exit 0
    fi
    if [ ! -e "$LAST_SUCCESS" ] && [ -n "$(find "$STARTED" -mmin -1560 2>/dev/null)" ]; then
        exit 0
    fi
    echo "No backup has succeeded in the last 26 hours"
    exit 1
}

restore() {
    use_git
    if [ -d "$MEMORY/.git" ]; then
        log "Refusing to restore: $MEMORY already holds memory. Restore into a fresh memory-data volume."
        exit 1
    fi
    psql -tAc "SELECT 1" >/dev/null
    if [ "$(psql -tAc "SELECT to_regclass('public.members') IS NOT NULL")" = "t" ] \
        && [ "$(psql -tAc "SELECT EXISTS (SELECT 1 FROM members)")" = "t" ]; then
        log "Refusing to restore: the database already has members. Restore into a fresh db-data volume."
        exit 1
    fi
    log "Restoring the memory folder from $BACKUP_REMOTE"
    git clone -q --branch main "$BACKUP_REMOTE" "$MEMORY"
    git -C "$MEMORY" remote remove origin
    git -C "$MEMORY" config core.autocrlf false
    git -C "$MEMORY" config core.quotepath false
    log "Restoring the database"
    dump=$(mktemp -d)
    git clone -q --depth 1 --branch database "$BACKUP_REMOTE" "$dump"
    psql -q -v ON_ERROR_STOP=1 -f "$dump/shared_memory.sql" >/dev/null
    rm -rf "$dump" "$DATABASE_WORK"
    log "Restored. Start the server, then rebuild the search index: docker compose exec server shared-memory reindex"
}

case "${1:-schedule}" in
    schedule) schedule ;;
    now) backup_now ;;
    restore) restore ;;
    health) health ;;
    *) echo "usage: backup [schedule|now|restore|health]" >&2; exit 2 ;;
esac
