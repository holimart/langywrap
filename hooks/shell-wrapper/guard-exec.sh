#!/usr/bin/env bash
# Shell replacement for AI tools — calls guard.sh in exec mode.
# Use this as $SHELL when launching AI tools directly (without execwrap).
# guard.sh alone is check-only (validator). This wrapper adds execution.
exec "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/guard.sh" --exec "$@"
