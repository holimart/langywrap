#!/usr/bin/env bash
# =============================================================================
# execwrap.bash — Universal AI Tool Execution Wrapper
# =============================================================================
#
# SECURITY LAYERS (applied in this order):
#   Layer 1: Rules in .exec/settings.json     (deny/allow/rewrite, JSON-configurable)
#   Layer 2: .llmsec/guard.sh                 (execsec hardcoded patterns + audit log)
#            Installed by: /harden-wizard at Maximum level (--with-wrapper)
#   Layer 3: lib/langywrap/security/interceptors/intercept-enhanced.py
#            57-rule YAML set: systemctl, npm install, git reset --hard, etc.
#   Layer 4: tool-native hooks (.claude/hooks/ etc.)   — called via features.hooks
#   Layer 5: git hooks (.githooks/)                    — installed by harden-wizard
#
# MODES:
#   Launcher:  execwrap.bash <tool-name> [args...]
#              Sets SHELL=this-script, BASH_ENV=preload.sh, then runs the tool.
#              Every bash call the tool makes is then intercepted by this script.
#
#   Shell:     execwrap.bash -c "command"
#              Called by the wrapped tool as its $SHELL. Applies layers 1-3,
#              env loading, logging, tmux launch, debug info, adhoc script capture.
#
#   Check:     execwrap.bash --check "command"
#              Validates a command (exits 0=allowed, 1=blocked) WITHOUT executing.
#              Used by preload.sh DEBUG trap to avoid double-execution.
#
# CONFIGURATION: .exec/settings.json (single file, all behavior)
# DOCS:          .exec/README.md
#
# REQUIREMENTS:  bash 4+, jq (required), tmux (optional), python3+PyYAML (Layer 3)
# =============================================================================

set -euo pipefail

# Resolve paths robustly even when called as $SHELL
EXECWRAP_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PROJECT_DIR="$(cd "$EXECWRAP_DIR/.." && pwd)"
SETTINGS="$EXECWRAP_DIR/settings.json"
REAL_BASH="${EXECWRAP_REAL_BASH:-/bin/bash}"

# =============================================================================
# PREREQUISITES CHECK
# =============================================================================

if ! command -v jq &>/dev/null; then
  echo "[execwrap] ERROR: jq is required but not installed." >&2
  echo "[execwrap] Install: brew install jq  OR  apt install jq  OR  dnf install jq" >&2
  # Fall through to real bash to not block the tool entirely
  exec "$REAL_BASH" "$@"
fi

if [[ ! -f "$SETTINGS" ]]; then
  echo "[execwrap] WARNING: settings.json not found at $SETTINGS — running unguarded" >&2
  exec "$REAL_BASH" "$@"
fi

# =============================================================================
# SECURITY MESSAGE ROUTING
# Prefer /dev/tty: makes block messages visible to the human user even when the
# AI tool redirects the tool's own stderr. Falls back gracefully if no terminal.
# =============================================================================

_sec_run() {
  # Run a command, routing stderr to /dev/tty when available so security block
  # messages reach the human user even if the AI tool redirects stderr.
  # Use an actual write test (not just [[ -w /dev/tty ]]) because the file-attribute
  # check returns true even when the device is not accessible in this shell context,
  # causing "$@" 2>/dev/tty to fail with "No such device or address".
  if { : >/dev/tty; } 2>/dev/null; then
    "$@" 2>/dev/tty
  else
    "$@"
  fi
}

# =============================================================================
# FEATURE FLAG HELPERS
# Cached at startup. If settings.json changes, restart the wrapped tool.
# =============================================================================

_jq()  { jq -r "${1}" "$SETTINGS" 2>/dev/null || echo "null"; }
_jqb() { jq -r "${1}" "$SETTINGS" 2>/dev/null || echo "false"; }

FEAT_ENV_LOADING="$(_jqb   '.features.env_loading.enabled')"
FEAT_ENV_FILE="$(_jq       '.features.env_loading.env_file')"
FEAT_ADHOC="$(_jqb         '.features.adhoc_saving.enabled')"
FEAT_ADHOC_DIR="$(_jq      '.features.adhoc_saving.dir')"
FEAT_LOGGING="$(_jqb       '.features.logging.enabled')"
FEAT_LOG_DIR="$(_jq        '.features.logging.dir')"
FEAT_TMUX="$(_jqb          '.features.tmux.enabled')"
FEAT_TMUX_MODE="$(_jq      '.features.tmux.default_mode')"
FEAT_TMUX_SESSION="$(_jq   '.features.tmux.session_prefix')"
FEAT_HOOKS="$(_jqb         '.features.hooks.enabled')"
FEAT_LOCAL="$(_jqb         '.features.local_priority.enabled')"
FEAT_DEBUG="$(_jqb         '.features.debug_info.enabled')"
FEAT_HARDENING="$(_jqb     '.features.hardening.enabled')"
# Layer 2: guard.sh (harden-wizard shell wrapper — instantiated template)
FEAT_GUARD_ENABLED="$(_jqb '.features.hardening.guard.enabled')"
FEAT_GUARD_PATH="$(_jq     '.features.hardening.guard.path')"
# Layer 3: intercept-enhanced.py (57-rule YAML set)
FEAT_ICEPTOR_ENABLED="$(_jqb '.features.hardening.interceptor.enabled')"
FEAT_ICEPTOR_PATH="$(_jq     '.features.hardening.interceptor.path')"
# RTK output compression
FEAT_RTK_ENABLED="$(_jqb     '.features.rtk.enabled')"
FEAT_RTK_PATH="$(_jq         '.features.rtk.path')"

# =============================================================================
# UTILITIES
# =============================================================================

_log()   { echo "[execwrap] $*" >&2; }
_debug() { [[ "$FEAT_DEBUG" == "true" ]] && echo "[execwrap:debug] $*" >&2 || true; }

_block() {
  local cmd="$1" reason="$2" alternative="$3" layer="${4:-Layer 1}"
  echo "" >&2
  echo "┌─────────────────────────────────────────────────────────────┐" >&2
  printf "│  execwrap: COMMAND BLOCKED (%s)%*s│\n" "$layer" $((29 - ${#layer})) "" >&2
  echo "└─────────────────────────────────────────────────────────────┘" >&2
  echo "" >&2
  printf "  Command:     %s\n" "$cmd" >&2
  echo "" >&2
  printf "  Reason:      %s\n" "$reason" >&2
  echo "" >&2
  echo "  Alternative:" >&2
  printf "    %s\n" "$alternative" >&2
  echo "" >&2
  exit 1
}

# =============================================================================
# .ENV LOADING
# =============================================================================

_load_env() {
  [[ "$FEAT_ENV_LOADING" != "true" ]] && return 0
  local env_path="$PROJECT_DIR/$FEAT_ENV_FILE"
  if [[ -f "$env_path" ]]; then
    _debug "Loading $env_path"
    set -a
    # shellcheck disable=SC1090
    source "$env_path" 2>/dev/null || true
    set +a
  fi
}

# =============================================================================
# LOCAL BINARY PRIORITY
# Checks if ./<binary> exists before using PATH version.
# Applied before rule matching AND re-applied after each rewrite so that
# rewrite chains stack correctly (python → uv run python → ./uv run python).
# =============================================================================

_apply_local_priority() {
  local cmd="$1"
  [[ "$FEAT_LOCAL" != "true" ]] && echo "$cmd" && return 0

  local first_word="${cmd%% *}"
  local rest="${cmd#"$first_word"}"

  local binary
  while IFS= read -r binary; do
    [[ -z "$binary" || "$binary" == "null" ]] && continue
    if [[ "$first_word" == "$binary" && -x "$PROJECT_DIR/$binary" ]]; then
      _debug "Local priority: $binary → ./$binary"
      echo "./$binary$rest"
      return 0
    fi
  done < <(jq -r '.features.local_priority.binaries[]?' "$SETTINGS" 2>/dev/null)

  echo "$cmd"
}

# =============================================================================
# RULE MATCHING
# Returns the rule index (0-based) of the first matching enabled rule, or -1
# =============================================================================

_match_rule() {
  local cmd="$1"
  local total idx enabled glob_pat regex_pat matched

  total="$(jq '.rules | length' "$SETTINGS" 2>/dev/null || echo 0)"

  for ((idx=0; idx<total; idx++)); do
    enabled="$(jq -r ".rules[$idx].enabled" "$SETTINGS" 2>/dev/null || echo false)"
    [[ "$enabled" != "true" ]] && continue

    glob_pat="$(jq -r ".rules[$idx].match.glob // empty" "$SETTINGS" 2>/dev/null || true)"
    regex_pat="$(jq -r ".rules[$idx].match.regex // empty" "$SETTINGS" 2>/dev/null || true)"

    matched=false

    if [[ -n "$glob_pat" && "$glob_pat" != "null" ]]; then
      # shellcheck disable=SC2254
      case "$cmd" in
        $glob_pat) matched=true ;;
      esac
    fi

    if [[ "$matched" != "true" && -n "$regex_pat" && "$regex_pat" != "null" ]]; then
      if echo "$cmd" | grep -qE "$regex_pat" 2>/dev/null; then
        matched=true
      fi
    fi

    if [[ "$matched" == "true" ]]; then
      echo "$idx"
      return 0
    fi
  done

  echo "-1"
}

# =============================================================================
# COMMAND REWRITING
# =============================================================================

_apply_rewrite() {
  local cmd="$1" rule_idx="$2"
  local prepend append replace replace_binary

  prepend="$(jq -r ".rules[$rule_idx].rewrite.prepend // empty" "$SETTINGS" 2>/dev/null || true)"
  append="$(jq -r ".rules[$rule_idx].rewrite.append // empty"   "$SETTINGS" 2>/dev/null || true)"
  replace="$(jq -r ".rules[$rule_idx].rewrite.replace // empty" "$SETTINGS" 2>/dev/null || true)"
  replace_binary="$(jq -r ".rules[$rule_idx].rewrite.replace_binary // empty" "$SETTINGS" 2>/dev/null || true)"

  # replace_binary: strips the first word (binary, even with path prefix like ./.venv/bin/python)
  # and substitutes replace_binary, keeping any arguments intact.
  # Example: "./.venv/bin/python script.py" → "uv run python script.py"
  if [[ -n "$replace_binary" && "$replace_binary" != "null" ]]; then
    local rest="${cmd#* }"
    [[ "$rest" == "$cmd" ]] && rest=""  # no args — bare invocation
    if [[ -n "$rest" ]]; then
      cmd="$replace_binary $rest"
    else
      cmd="$replace_binary"
    fi
  fi

  [[ -n "$replace" && "$replace" != "null" ]] && cmd="$replace"
  [[ -n "$prepend" && "$prepend" != "null" ]] && cmd="$prepend $cmd"
  [[ -n "$append"  && "$append"  != "null" ]] && cmd="$cmd $append"

  echo "$cmd"
}

# =============================================================================
# ADHOC SCRIPT CAPTURE
# Detects and saves inline scripts for later analysis.
# Sets _ADHOC_SAVED_FILE (global) so debug banner can report the path.
# =============================================================================

_ADHOC_SAVED_FILE=""  # reset per shell-mode invocation

_save_adhoc() {
  local cmd="$1"
  [[ "$FEAT_ADHOC" != "true" ]] && return 0

  local adhoc_dir="$PROJECT_DIR/$FEAT_ADHOC_DIR"
  mkdir -p "$adhoc_dir"

  local ts pid content ext
  ts="$(date '+%Y%m%d_%H%M%S')"
  pid="$$"
  content=""
  ext=""

  if echo "$cmd" | grep -qE '^bash\s+-c\s+'; then
    content="${cmd#bash -c }"
    content="${content#\'}"; content="${content%\'}"
    ext="sh"
  elif echo "$cmd" | grep -qE '^(python3?|python)\s+-c\s+'; then
    content="${cmd#*-c }"
    content="${content#\'}"; content="${content%\'}"
    ext="py"
  elif echo "$cmd" | grep -qE '<<<|<<[-]?\s*(EOF|END|HEREDOC)'; then
    content="$cmd"
    ext="sh"
  else
    return 0
  fi

  local fname="$adhoc_dir/${ts}_${pid}.${ext}"
  {
    printf '# ExecWrap adhoc script capture\n'
    printf '# Timestamp: %s  PID: %s\n' "$ts" "$pid"
    printf '# Original:  %s\n' "$cmd"
    printf '# ---\n'
    printf '%s\n' "$content"
  } > "$fname"

  _ADHOC_SAVED_FILE="$fname"
  _debug "Adhoc script saved: $fname"
}

# =============================================================================
# HOOK EXECUTION (Layer 4 — tool-native hooks)
# Calls pre-bash / pre-command hooks installed by harden-wizard
# =============================================================================

_run_hooks() {
  local cmd="$1"
  [[ "$FEAT_HOOKS" != "true" ]] && return 0

  local hook_dir hook_path
  while IFS= read -r hook_dir; do
    [[ -z "$hook_dir" || "$hook_dir" == "null" ]] && continue
    hook_path="$PROJECT_DIR/$hook_dir"
    [[ ! -d "$hook_path" ]] && continue

    for hook in "$hook_path"/pre-bash "$hook_path"/pre-command "$hook_path"/PreToolUse; do
      if [[ -x "$hook" ]]; then
        _debug "Layer 4 hook: $hook"
        "$hook" "$cmd" 2>/dev/null || true
      fi
    done
  done < <(jq -r '.features.hooks.dirs[]?' "$SETTINGS" 2>/dev/null)
}

# =============================================================================
# LOG FILE SETUP
# =============================================================================

_setup_log() {
  [[ "$FEAT_LOGGING" != "true" ]] && echo "" && return 0

  local log_dir="$PROJECT_DIR/$FEAT_LOG_DIR"
  mkdir -p "$log_dir"

  local ts pid safe_cmd
  ts="$(date '+%Y%m%d_%H%M%S')"
  pid="$$"
  safe_cmd="$(echo "${1:0:40}" | tr -cs '[:alnum:]._-' '_')"

  echo "$log_dir/${ts}_${pid}_${safe_cmd}.log"
}

# =============================================================================
# TMUX EXECUTION
# =============================================================================

_tmux_mode_for_rule() {
  local rule_idx="$1"
  if [[ "$rule_idx" == "-1" ]]; then
    echo "$FEAT_TMUX_MODE"
    return 0
  fi

  local rule_tmux
  rule_tmux="$(jq -r ".rules[$rule_idx].tmux // \"$FEAT_TMUX_MODE\"" "$SETTINGS" 2>/dev/null || echo "$FEAT_TMUX_MODE")"
  [[ "$rule_tmux" == "null" ]] && echo "$FEAT_TMUX_MODE" || echo "$rule_tmux"
}

_run_in_tmux() {
  local cmd="$1" log_file="$2" mode="$3"

  if ! command -v tmux &>/dev/null; then
    _debug "tmux not found, running directly"
    return 1
  fi

  local session="${FEAT_TMUX_SESSION}"
  local ts pid window_name full_cmd
  ts="$(date '+%H%M%S')"
  pid="$$"
  window_name="${ts}_${pid}"

  if [[ -n "$log_file" ]]; then
    full_cmd="{ $cmd; } 2>&1 | tee '$log_file'; echo '[execwrap] exit \$?' >> '$log_file'"
  else
    full_cmd="$cmd"
  fi

  if [[ "$FEAT_DEBUG" == "true" ]]; then
    local short_cmd="${cmd:0:50}"
    echo "" >&2
    echo "┌─────────────────────────────────────────────────────────────┐" >&2
    echo "│  execwrap: launching in tmux                                │" >&2
    echo "├─────────────────────────────────────────────────────────────┤" >&2
    printf "│  PID:      %-48s│\n" "$pid" >&2
    printf "│  Session:  %-48s│\n" "$session:$window_name" >&2
    [[ -n "$log_file" ]] && printf "│  Log:      %-48s│\n" "$(basename "$log_file")" >&2
    printf "│  Command:  %-48s│\n" "$short_cmd" >&2
    echo "├─────────────────────────────────────────────────────────────┤" >&2
    printf "│  Watch:    tmux attach -t %-34s│\n" "$session" >&2
    printf "│  Window:   tmux select-window -t %s:%-19s│\n" "$session" "$window_name" >&2
    echo "└─────────────────────────────────────────────────────────────┘" >&2
    echo "" >&2
  fi

  if [[ "$mode" == "session" ]]; then
    local sess_name="${session}_${window_name}"
    tmux new-session -d -s "$sess_name" -x 220 -y 50 "$REAL_BASH" -c "$full_cmd" 2>/dev/null || return 1
    _log "Running in tmux session: $sess_name"
  else
    tmux new-session -d -s "$session" -x 220 -y 50 2>/dev/null || true
    tmux new-window -t "$session" -n "$window_name" "$REAL_BASH" -c "$full_cmd" 2>/dev/null || return 1
    _log "Running in tmux window: $session:$window_name"
  fi

  return 0
}

# =============================================================================
# EXECSEC LAYERS 2 + 3
# Layer 2: .llmsec/guard.sh     — hardcoded grep patterns, installed by harden-wizard
# Layer 3: intercept-enhanced.py — 57-rule YAML permissions set
#
# These run AFTER Layer 1 (execwrap rules). A command must pass all three layers.
# Redundancy is intentional — defence in depth.
#
# Block messages are routed via _sec_run() which uses /dev/tty when available,
# so the human user sees why a command was blocked even if the AI tool's stdout
# is redirected. Falls back gracefully in non-interactive environments.
# =============================================================================

_run_execsec_layers() {
  local cmd="$1"
  [[ "$FEAT_HARDENING" != "true" ]] && return 0

  # ------------------------------------------------------------------
  # Layer 2: guard.sh (harden-wizard instantiated shell wrapper)
  # Adds: secret file access via cat/tar/zip, scp/rsync on credentials,
  #       dd blocking, case-insensitive exfiltration, audit log to ~/.llmsec/
  # ------------------------------------------------------------------
  if [[ "$FEAT_GUARD_ENABLED" == "true" ]]; then
    local guard_path="$PROJECT_DIR/$FEAT_GUARD_PATH"

    if [[ -x "$guard_path" ]]; then
      # Sanity check: ensure it was instantiated (not the raw template)
      if grep -q '__REAL_SHELL__' "$guard_path" 2>/dev/null; then
        _log "WARNING: Layer 2 guard.sh contains uninstantiated template placeholder __REAL_SHELL__"
        _log "         Run /harden-wizard at Maximum security level to fix this."
      else
        _debug "Layer 2 (guard.sh): $guard_path"
        # guard.sh defaults to check-only — no --exec needed (we don't want it to execute)
        # _sec_run routes stderr to /dev/tty when available so block messages reach the user
        if ! _sec_run "$guard_path" -c "$cmd"; then
          echo "" >&2
          echo "┌─────────────────────────────────────────────────────────────┐" >&2
          echo "│  execwrap: BLOCKED (Layer 2 — execsec guard.sh)             │" >&2
          echo "└─────────────────────────────────────────────────────────────┘" >&2
          echo "  See above for details. Audit log: ~/.llmsec/logs/" >&2
          exit 1
        fi
      fi
    else
      _debug "Layer 2 skipped: guard not found at $guard_path"
      _debug "  Install with: /harden-wizard (Maximum security level, --with-wrapper)"
    fi
  fi

  # ------------------------------------------------------------------
  # Layer 3: intercept-enhanced.py (full 57-rule YAML permissions set)
  # Adds rules NOT in Layer 1 or 2: systemctl, shutdown, reboot,
  #       npm/pip/yarn install (ask), git reset --hard (ask),
  #       docker run/rm (ask), mount/umount, mkfs, editors (allow+log)
  #
  # Config discovery: intercept-enhanced.py searches automatically for
  # permissions.yaml in: .settings/, .claude/, .opencode/, ~/.llmsec/defaults/,
  # lib/langywrap/security/defaults/. To customize, create .settings/permissions.yaml.
  # ------------------------------------------------------------------
  if [[ "$FEAT_ICEPTOR_ENABLED" == "true" ]]; then
    local interceptor_path="$PROJECT_DIR/$FEAT_ICEPTOR_PATH"

    if [[ -x "$interceptor_path" ]] || [[ -f "$interceptor_path" ]]; then
      if command -v python3 &>/dev/null; then
        _debug "Layer 3 (intercept-enhanced.py): $interceptor_path"
        # _sec_run routes block messages to /dev/tty when available
        if ! _sec_run python3 "$interceptor_path" "$cmd"; then
          echo "" >&2
          echo "┌─────────────────────────────────────────────────────────────┐" >&2
          echo "│  execwrap: BLOCKED (Layer 3 — intercept-enhanced.py)        │" >&2
          echo "└─────────────────────────────────────────────────────────────┘" >&2
          echo "  See above for details. Config: lib/langywrap/security/defaults/permissions.yaml" >&2
          exit 1
        fi
      else
        _debug "Layer 3 skipped: python3 not found"
      fi
    else
      _debug "Layer 3 skipped: interceptor not found at $interceptor_path"
      _debug "  Initialize execsec submodule: git submodule update --init execsec"
    fi
  fi
}

# =============================================================================
# RTK OUTPUT COMPRESSION
# Rewrites commands through RTK for token-optimized output when the result
# goes to an LLM context. Uses `rtk rewrite` which already handles:
#   - Compound commands (&&, ||, ;) — rewrites each segment
#   - Pipes (|) — only rewrites pre-pipe segment, leaves downstream alone
#   - Heredocs (<<) — skips entirely
#   - Redirects (2>&1, >/dev/null) — strips before matching, re-appends
#   - Already-RTK commands — passes through unchanged
#   - Unsupported commands — returns exit 1, no rewrite
# =============================================================================

_rtk_rewrite() {
  local cmd="$1"
  [[ "$FEAT_RTK_ENABLED" != "true" ]] && echo "$cmd" && return 0

  # Resolve RTK binary: configured path, .exec/rtk, or PATH
  local rtk_bin=""
  if [[ -n "$FEAT_RTK_PATH" && "$FEAT_RTK_PATH" != "null" && -x "$PROJECT_DIR/$FEAT_RTK_PATH" ]]; then
    rtk_bin="$PROJECT_DIR/$FEAT_RTK_PATH"
  elif [[ -x "$EXECWRAP_DIR/rtk" ]]; then
    rtk_bin="$EXECWRAP_DIR/rtk"
  elif command -v rtk &>/dev/null; then
    rtk_bin="$(command -v rtk)"
  fi

  if [[ -z "$rtk_bin" ]]; then
    _debug "RTK: binary not found, skipping compression"
    echo "$cmd"
    return 0
  fi

  # Delegate to RTK's rewrite engine (src/discover/registry.rs)
  # Exit 0 + stdout = rewritten command
  # Exit 1 = no RTK equivalent, pass through
  # Exit 2 = deny (handled by security layers already)
  # Exit 3 = ask (rewritten but needs confirmation — we treat as rewrite)
  local rewritten exit_code
  rewritten=$("$rtk_bin" rewrite "$cmd" 2>/dev/null) || true
  exit_code=$?

  case $exit_code in
    0|3)
      if [[ -n "$rewritten" && "$rewritten" != "$cmd" ]]; then
        _debug "RTK rewrite: '$cmd' → '$rewritten'"
        echo "$rewritten"
        return 0
      fi
      ;;
  esac

  # No rewrite — return original
  echo "$cmd"
}

# =============================================================================
# CHECK MODE  ── validate command without executing (used by preload.sh DEBUG trap)
# Returns 0 if allowed, 1 if blocked. Does NOT execute the command.
# =============================================================================

if [[ "${1:-}" == "--check" ]]; then
  shift
  CMD="${*}"
  [[ -z "$CMD" ]] && exit 0

  _load_env
  CMD="$(_apply_local_priority "$CMD")"
  RULE_IDX="$(_match_rule "$CMD")"

  # Apply Layer 1 check (deny/rewrite only — no ask, no execution)
  if [[ "$RULE_IDX" != "-1" ]]; then
    ACTION="$(jq -r ".rules[$RULE_IDX].action" "$SETTINGS")"
    case "$ACTION" in
      deny)
        REASON="$(jq -r ".rules[$RULE_IDX].reason // \"blocked\"" "$SETTINGS")"
        ALT="$(jq -r ".rules[$RULE_IDX].alternative // \"\"" "$SETTINGS")"
        _block "$CMD" "$REASON" "$ALT" "Layer 1 — settings.json"
        ;;
      rewrite)
        CMD="$(_apply_rewrite "$CMD" "$RULE_IDX")"
        # Re-apply local priority after rewrite (uv → ./uv, etc.)
        CMD="$(_apply_local_priority "$CMD")"
        ;;
    esac
  fi

  # Layers 2+3 check (check-only by default — no --exec flag needed)
  _run_execsec_layers "$CMD"
  exit 0  # allowed — caller (bash trap) will let original command execute
fi

# =============================================================================
# SHELL MODE  ── called as $SHELL by the wrapped tool
# =============================================================================

if [[ "${1:-}" == "-c" ]]; then
  shift
  CMD="${*}"
  [[ -z "$CMD" ]] && exec "$REAL_BASH" -c ""

  # Step 1: Load .env
  _load_env

  # Step 2: Apply local binary priority (./just over just, etc.)
  CMD="$(_apply_local_priority "$CMD")"

  # Step 3: Layer 1 — match against settings.json rules
  RULE_IDX="$(_match_rule "$CMD")"

  if [[ "$RULE_IDX" != "-1" ]]; then
    ACTION="$(jq -r ".rules[$RULE_IDX].action" "$SETTINGS")"
    RULE_ID="$(jq -r ".rules[$RULE_IDX].id" "$SETTINGS")"
    _debug "Layer 1 rule '$RULE_ID' matched (action: $ACTION)"

    case "$ACTION" in
      deny)
        REASON="$(jq -r ".rules[$RULE_IDX].reason // \"No reason specified\"" "$SETTINGS")"
        ALT="$(jq -r ".rules[$RULE_IDX].alternative // \"No alternative specified\"" "$SETTINGS")"
        _block "$CMD" "$REASON" "$ALT" "Layer 1 — settings.json"
        ;;
      rewrite)
        NEW_CMD="$(_apply_rewrite "$CMD" "$RULE_IDX")"
        _debug "Layer 1 rewrite: '$CMD' → '$NEW_CMD'"
        CMD="$NEW_CMD"
        # IMPORTANT: Re-apply local priority after rewrite so chains stack correctly.
        # Example: python script.py → rewrite → uv run python script.py
        #          → local_priority → ./uv run python script.py
        #          → re-match → may hit tmux-uv-run-python-scripts rule
        CMD="$(_apply_local_priority "$CMD")"
        _debug "After re-priority: '$CMD'"
        # Re-match after rewrite + re-priority (may hit tmux or different rule)
        RULE_IDX="$(_match_rule "$CMD")"
        ;;
      ask)
        echo "" >&2
        echo "[execwrap] CONFIRM (Layer 1 — ask rule): About to run:" >&2
        echo "  $CMD" >&2
        printf "Proceed? [y/N] " >&2
        read -r -t 30 ANSWER </dev/tty || ANSWER="n"
        [[ "${ANSWER,,}" != "y" ]] && { echo "[execwrap] Cancelled." >&2; exit 1; }
        ;;
      allow|*)
        : # allow through
        ;;
    esac
  fi

  # Step 4: Layers 2 + 3 — execsec guard.sh and intercept-enhanced.py
  _run_execsec_layers "$CMD"

  # Step 5: RTK output compression — rewrite command for token savings
  # Runs AFTER security (Layers 1-3) so denied commands never reach RTK.
  # Runs BEFORE execution so the LLM sees compressed output.
  CMD="$(_rtk_rewrite "$CMD")"

  # Step 6: Save adhoc scripts (bash -c, python -c, heredocs)
  # Must happen before debug banner so _ADHOC_SAVED_FILE is set
  _save_adhoc "$CMD"

  # Step 7: Layer 4 — run tool-native hooks (installed by harden-wizard)
  _run_hooks "$CMD"

  # Step 8: Setup log file
  LOG_FILE="$(_setup_log "$CMD")"

  # Step 9: Determine tmux mode for this command
  TMUX_MODE="$(_tmux_mode_for_rule "$RULE_IDX")"

  # Step 10: Execute (via tmux if enabled, else directly with tee)
  if [[ "$FEAT_TMUX" == "true" && "$TMUX_MODE" != "none" && "$TMUX_MODE" != "false" && "$TMUX_MODE" != "null" ]]; then
    if _run_in_tmux "$CMD" "$LOG_FILE" "$TMUX_MODE"; then
      exit 0
    fi
  fi

  # Non-tmux debug info
  if [[ "$FEAT_DEBUG" == "true" ]]; then
    echo "" >&2
    echo "┌─────────────────────────────────────────────────────────────┐" >&2
    echo "│  execwrap: executing                                        │" >&2
    echo "├─────────────────────────────────────────────────────────────┤" >&2
    printf "│  PID:     %-49s│\n" "$$" >&2
    printf "│  Cmd:     %-49s│\n" "${CMD:0:48}" >&2
    [[ -n "$LOG_FILE" ]] && printf "│  Log:     %-49s│\n" "$(basename "$LOG_FILE")" >&2
    [[ -n "${_ADHOC_SAVED_FILE:-}" ]] && printf "│  Adhoc:   %-49s│\n" "$(basename "$_ADHOC_SAVED_FILE")" >&2
    echo "└─────────────────────────────────────────────────────────────┘" >&2
    echo "" >&2
  fi

  if [[ -n "$LOG_FILE" ]]; then
    exec "$REAL_BASH" -c "{ $CMD; } 2>&1 | tee '$LOG_FILE'"
  else
    exec "$REAL_BASH" -c "$CMD"
  fi

  exit 0
fi

# =============================================================================
# LAUNCHER MODE  ── execwrap.bash <tool> [args...]
# =============================================================================

TOOL="${1:-}"

if [[ -z "$TOOL" ]]; then
  cat >&2 <<'USAGE'
execwrap.bash — Universal AI Tool Execution Wrapper

SECURITY LAYERS ACTIVE:
  Layer 1: .exec/settings.json rules       (JSON-configurable deny/allow/rewrite)
  Layer 2: .llmsec/guard.sh                (execsec hardened patterns + audit log)
  Layer 3: intercept-enhanced.py           (57-rule YAML permissions set)
  Layer 4: tool-native hooks               (.claude/hooks/, .cursor/hooks/, etc.)
  Layer 5: git hooks                       (.githooks/ pre-commit/pre-push)

Usage:
  execwrap.bash <tool> [args...]   Launch a tool with all layers active
  execwrap.bash -c "command"       Shell mode (called internally by wrapped tool)
  execwrap.bash --check "command"  Check-only mode (validate without executing)

Examples:
  execwrap.bash claude              Wrap Claude Code (~/.local/bin/claude)
  execwrap.bash opencode            Wrap OpenCode (~/.opencode/bin/opencode)
  execwrap.bash bash                Open a wrapped bash shell for testing

Configuration: .exec/settings.json
Documentation: .exec/README.md
USAGE
  exit 1
fi

shift

WRAPPER_PATH="$(readlink -f "${BASH_SOURCE[0]}")"

_log "Wrapping: $TOOL $*"
_log "Layer 1:  settings.json rules"
_log "Layer 2:  ${PROJECT_DIR}/${FEAT_GUARD_PATH} (guard enabled: ${FEAT_GUARD_ENABLED})"
_log "Layer 3:  ${PROJECT_DIR}/${FEAT_ICEPTOR_PATH} (interceptor enabled: ${FEAT_ICEPTOR_ENABLED})"
_log "Layer 4:  tool-native hooks (hooks enabled: ${FEAT_HOOKS})"
_log "SHELL=    $WRAPPER_PATH"
_log "BASH_ENV= $EXECWRAP_DIR/preload.sh"

_load_env

export SHELL="$WRAPPER_PATH"
export BASH="$WRAPPER_PATH"
export EXECWRAP_REAL_BASH="${REAL_BASH}"
export BASH_ENV="$EXECWRAP_DIR/preload.sh"
export EXECWRAP_PROJECT_DIR="$PROJECT_DIR"
export EXECWRAP_ACTIVE=1

exec "$TOOL" "$@"
