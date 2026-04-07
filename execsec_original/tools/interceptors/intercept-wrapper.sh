#!/usr/bin/env bash
# Shell wrapper for AI tools — intercept-enhanced.py in exec mode.
# Installed as $SHELL by secure-run.sh. Checks AND executes.
#
# When bash calls $SHELL it uses: $SHELL -c "command_string"
# We strip the -c and pass the command string directly to the interceptor.
_self="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/intercept-enhanced.py"
if [[ "${1:-}" == "-c" ]]; then shift; fi  # strip the -c that bash passes
exec python3 "$_self" --exec "$@"
