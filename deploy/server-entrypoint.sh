#!/bin/sh
# Runs the server image's command as the unprivileged user shared-memory, never as root (#388).
#
# The container starts as root only to hand /data to that user: a volume made before the image stopped running as root,
# or a memory folder restored into the volume by root (the backup container, a host's own restore), holds root's files,
# and git refuses a repository another user owns. Only what is mis-owned changes, so a start over a volume already
# handed over changes nothing. Then the command replaces this script, so it stays the container's first process.
#
# `docker compose exec` skips this script and runs as root. The commands run that way (install-license, count-members,
# reindex, link-github, setup) write the database, not /data, and the image tells git to trust /data/memory for them.
set -eu

DATA="${SHARED_MEMORY_DATA:-/data}"
USER_NAME=shared-memory

if [ "$(id -u)" != 0 ]; then
    exec "$@"
fi

uid=$(id -u "$USER_NAME")
gid=$(id -g "$USER_NAME")
if [ -d "$DATA" ]; then
    find "$DATA" \( ! -user "$uid" -o ! -group "$gid" \) -exec chown -h "$uid:$gid" {} +
fi

HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
export HOME
exec setpriv --reuid="$uid" --regid="$gid" --init-groups -- "$@"
