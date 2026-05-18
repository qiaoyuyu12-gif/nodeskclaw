#!/bin/sh
ENV_FILE="/host-config/.env"
if [ -f "$ENV_FILE" ]; then
    _tmp=$(mktemp)
    tr -d '\r' < "$ENV_FILE" > "$_tmp"
    set -af
    . "$_tmp"
    set +af
    rm -f "$_tmp"
fi
exec "$@"
