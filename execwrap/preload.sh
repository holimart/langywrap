#!/usr/bin/env bash
# =============================================================================
# preload.sh — BASH_ENV trap installer
# =============================================================================
#
# Loaded via BASH_ENV into every non-interactive bash spawned by the wrapped
# tool. Installs a DEBUG trap that intercepts commands BEFORE they execute —
# including each stage of pipes and every statement in multiline scripts.
#
# Both interception mechanisms work together:
#   SHELL=-c "cmd"   →  execwrap.bash sees the outer command string
#   BASH_ENV trap    →  intercepts individual commands within running scripts
#                       (catches things SHELL=-c misses: pipe stages, loops, etc.)
#
# IMPORTANT: This file is sourced into every bash subshell. Keep it fast and
# side-effect-free. The __EXECWRAP_ACTIVE guard prevents double-installation.
# =============================================================================

[[ "${__EXECWRAP_ACTIVE:-}" == "1" ]] && return 0
export __EXECWRAP_ACTIVE=1

__EXECWRAP_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
__EXECWRAP_WRAPPER="$__EXECWRAP_DIR/execwrap.bash"

[[ ! -x "$__EXECWRAP_WRAPPER" ]] && return 0

__execwrap_debug_trap() {
  local cmd="$BASH_COMMAND"

  # Skip our own functions to avoid infinite recursion
  [[ "$cmd" == __execwrap_* ]] && return 0
  [[ "$cmd" =~ EXECWRAP ]]     && return 0
  [[ -z "$cmd" ]]              && return 0

  # Skip shell builtins and structural statements that aren't executable commands
  case "$cmd" in
    local\ *|export\ *|declare\ *|readonly\ *|unset\ *|\
    true|false|:|return\ *|exit\ *|\[*|\[\[*|test\ *|\
    source\ *|\.\ *|set\ *|shopt\ *|trap\ *) return 0 ;;
  esac

  # Validate command using --check mode (exits 0=allowed, 1=blocked).
  # On exit 0: bash continues and runs the original command itself — no double-execution.
  # On exit 1: we kill the process group to abort the pipeline/script cleanly.
  if ! "$__EXECWRAP_WRAPPER" --check "$cmd" 2>&1; then
    kill -TERM 0 2>/dev/null || true
    return 1
  fi
}

trap '__execwrap_debug_trap' DEBUG

# Propagate BASH_ENV to child bash processes
export BASH_ENV="${BASH_ENV:-$__EXECWRAP_DIR/preload.sh}"
