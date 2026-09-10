#!/bin/sh
# Drop to PUID/PGID, apply UMASK, make /config writable, then exec the CLI.
# Commands: cron (default, in-process scheduler honouring SCHEDULE), once, healthcheck.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
UMASK="${UMASK:-022}"
CONFIG_DIR="${CONFIG_DIR:-/config}"

if [ "$(id -u)" = "0" ]; then
    if [ "$(id -g app)" != "$PGID" ]; then groupmod -o -g "$PGID" app; fi
    if [ "$(id -u app)" != "$PUID" ]; then usermod -o -u "$PUID" app; fi
    mkdir -p "$CONFIG_DIR/cache" "$CONFIG_DIR/state" "$CONFIG_DIR/log"
    # only fix ownership of what the tool itself creates; never recurse into user files blindly
    chown app:app "$CONFIG_DIR" "$CONFIG_DIR/cache" "$CONFIG_DIR/state" "$CONFIG_DIR/log" 2>/dev/null || true
    for f in "$CONFIG_DIR"/cache/* "$CONFIG_DIR"/state/* "$CONFIG_DIR"/log/*; do
        [ -e "$f" ] && chown app:app "$f" 2>/dev/null || true
    done
    # example curation files, for copying by hand; never loaded automatically
    mkdir -p "$CONFIG_DIR/examples" && cp /app/examples/* "$CONFIG_DIR/examples/" 2>/dev/null || true
    chown -R app:app "$CONFIG_DIR/examples" 2>/dev/null || true
    umask "$UMASK"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups plex-regional-titles "$@"
fi

umask "$UMASK"
exec plex-regional-titles "$@"
