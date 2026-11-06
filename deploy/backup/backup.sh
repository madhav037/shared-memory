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
#
# With BACKUP_AGE_RECIPIENT set (an age public key), nothing readable leaves the server: branch database holds
# shared_memory.sql.age and memory.bundle.age (the memory history as a git bundle), each encrypted to that key, and
# there is no main branch. Restoring needs the matching identity (private key) at BACKUP_AGE_IDENTITY.
set -euo pipefail

# The defaults are the container's paths; the tests point them at a temporary directory.
MEMORY=${MEMORY:-/data/memory}
BACKUPS=${BACKUPS:-/backups}
DATABASE_WORK=$BACKUPS/database
LAST_SUCCESS=$BACKUPS/last-success
STARTED=/tmp/started
KEY=${BACKUP_KEY:-/run/secrets/backup_key}
AGE_RECIPIENT=${BACKUP_AGE_RECIPIENT:-}
AGE_IDENTITY=${BACKUP_AGE_IDENTITY:-/run/secrets/age_identity}
# A temporary folder for what must never be left lying about readable: the plain dump and bundle, the decrypted ones.
PLAIN=

log() { echo "$(date -Is) $*"; }

clean_up() {
    if [ -n "$PLAIN" ]; then
        rm -rf "$PLAIN"
    fi
}
trap clean_up EXIT

use_git() {
    git config --global --add safe.directory '*'
    git config --global user.name "Shared Memory backup"
    git config --global user.email "backup@shared-memory.invalid"
    if [ -f "$KEY" ] && [ -s "$KEY" ]; then
        # ssh refuses a key readable by others, which a mounted file often is.
        install -m 600 "$KEY" /tmp/backup_key
        export GIT_SSH_COMMAND="ssh -i /tmp/backup_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$BACKUPS/known_hosts"
    fi
}

backup_now() {
    use_git
    log "Backup started"
    if [ -n "$AGE_RECIPIENT" ]; then
        command -v age >/dev/null || { log "BACKUP_AGE_RECIPIENT is set but age is not installed"; exit 1; }
        log "Backups are encrypted with age before they leave the server"
    else
        log "Backups are unencrypted: set SHARED_MEMORY_BACKUP_AGE_RECIPIENT to an age public key to encrypt them"
    fi
    if [ ! -d "$DATABASE_WORK/.git" ]; then
        git init -q -b database "$DATABASE_WORK"
        # Continue the remote's history, for example on a host restored from this backup.
        if git ls-remote --exit-code --heads "$BACKUP_REMOTE" database >/dev/null; then
            git -C "$DATABASE_WORK" fetch -q "$BACKUP_REMOTE" database
            git -C "$DATABASE_WORK" reset -q FETCH_HEAD
        fi
    fi
    if [ -n "$AGE_RECIPIENT" ]; then
        backup_encrypted
    else
        backup_plain
    fi
    touch "$LAST_SUCCESS"
    log "Backup finished"
}

commit_database_work() {
    if ! git -C "$DATABASE_WORK" diff --cached --quiet; then
        git -C "$DATABASE_WORK" commit -q -m "Database backup $(date -Is)"
    fi
    git -C "$DATABASE_WORK" push -q "$BACKUP_REMOTE" HEAD:database
}

backup_plain() {
    # Dump the database before pushing memory, so every memory the dump refers to is already in the push.
    pg_dump --clean --if-exists --no-owner --exclude-table-data=sections -f "$DATABASE_WORK/shared_memory.sql"
    git -C "$DATABASE_WORK" add shared_memory.sql
    commit_database_work
    # The server creates the repository at start, but main has no commit until the first memory is saved.
    if git -C "$MEMORY" rev-parse --verify -q main >/dev/null 2>&1; then
        git -C "$MEMORY" push -q "$BACKUP_REMOTE" main
    else
        log "The memory folder has no saved memory yet: nothing to push"
    fi
}

# The dump and the memory history go into one commit on branch database, so a dump never refers to a memory the
# backup lacks. The plain dump and bundle exist only in a temporary folder. A plain dump left in the work folder by an
# earlier, unencrypted backup is dropped from the new commit; it stays in older commits and on a remote's main branch,
# which docs/deployment.md says to delete.
backup_encrypted() {
    PLAIN=$(mktemp -d)
    pg_dump --clean --if-exists --no-owner --exclude-table-data=sections -f "$PLAIN/shared_memory.sql"
    age -r "$AGE_RECIPIENT" -o "$DATABASE_WORK/shared_memory.sql.age" "$PLAIN/shared_memory.sql"
    git -C "$DATABASE_WORK" rm -q -f --ignore-unmatch shared_memory.sql
    git -C "$DATABASE_WORK" add shared_memory.sql.age
    if git -C "$MEMORY" rev-parse --verify -q main >/dev/null 2>&1; then
        git -C "$MEMORY" bundle create -q "$PLAIN/memory.bundle" main
        age -r "$AGE_RECIPIENT" -o "$DATABASE_WORK/memory.bundle.age" "$PLAIN/memory.bundle"
        git -C "$DATABASE_WORK" add memory.bundle.age
    else
        log "The memory folder has no saved memory yet: no bundle to encrypt"
    fi
    commit_database_work
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
    PLAIN=$(mktemp -d)
    git clone -q --depth 1 --branch database "$BACKUP_REMOTE" "$PLAIN/database"
    if [ -f "$PLAIN/database/shared_memory.sql.age" ]; then
        restore_encrypted
    else
        restore_plain
    fi
    rm -rf "$DATABASE_WORK"
    log "Restored. Start the server, then rebuild the search index: docker compose exec server shared-memory reindex"
}

finish_memory_folder() {
    git -C "$MEMORY" remote remove origin
    git -C "$MEMORY" config core.autocrlf false
    git -C "$MEMORY" config core.quotepath false
}

restore_plain() {
    log "Restoring the memory folder from $BACKUP_REMOTE"
    git clone -q --branch main "$BACKUP_REMOTE" "$MEMORY"
    finish_memory_folder
    log "Restoring the database"
    psql -q -v ON_ERROR_STOP=1 -f "$PLAIN/database/shared_memory.sql" >/dev/null
}

restore_encrypted() {
    if [ ! -s "$AGE_IDENTITY" ]; then
        log "Refusing to restore: this backup is encrypted and the age identity (private key) is not at $AGE_IDENTITY"
        exit 1
    fi
    # Decrypt everything before changing anything, so a wrong identity leaves the folder and database untouched.
    age -d -i "$AGE_IDENTITY" -o "$PLAIN/shared_memory.sql" "$PLAIN/database/shared_memory.sql.age"
    if [ -f "$PLAIN/database/memory.bundle.age" ]; then
        age -d -i "$AGE_IDENTITY" -o "$PLAIN/memory.bundle" "$PLAIN/database/memory.bundle.age"
        log "Restoring the memory folder from the encrypted bundle"
        git clone -q --branch main "$PLAIN/memory.bundle" "$MEMORY"
        finish_memory_folder
    else
        log "The backup holds no memory history yet: leaving the memory folder for the server to create"
    fi
    log "Restoring the database"
    psql -q -v ON_ERROR_STOP=1 -f "$PLAIN/shared_memory.sql" >/dev/null
}

case "${1:-schedule}" in
    schedule) schedule ;;
    now) backup_now ;;
    restore) restore ;;
    health) health ;;
    *) echo "usage: backup [schedule|now|restore|health]" >&2; exit 2 ;;
esac
