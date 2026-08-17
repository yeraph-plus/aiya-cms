#!/bin/sh
set -eu

# The existing install command is idempotent. On an empty database it creates
# the administrator and prints the generated password once; on later restarts
# it resolves the existing user and never prints a replacement password.
if [ "${AIYA_AUTO_INSTALL:-false}" = "true" ] && [ "${1:-}" = "supervisord" ]; then
    echo "[aiya] running idempotent first-start installation"
    /opt/venv/bin/python -m inc.cli install
fi

exec "$@"
