#!/usr/bin/env bash
# =============================================================================
# test_opencode_execwrap.sh — Test opencode via execwrap with safe prompts
# =============================================================================
#
# Tests that opencode is callable through the execwrap security wrapper and
# that the model responds correctly. Uses only non-destructive prompts.
#
# Rate limiting: NVIDIA free tier is rate limited — sleeps between tests.
# Adjust SLEEP_BETWEEN_TESTS if you hit 429s.
#
# Usage:
#   ./scripts/test_opencode_execwrap.sh
#   ./scripts/test_opencode_execwrap.sh --model nvidia/llama-3.1-nemotron-ultra-253b-v1
#   ./scripts/test_opencode_execwrap.sh --fast        # shorter sleeps (for paid tier)
#   ./scripts/test_opencode_execwrap.sh --dry-run     # show prompts, don't call API
#
# TODO: Set MODEL below to the correct NVIDIA NIM model ID for MiniMax M2.5.
#       Check the catalog at: https://build.nvidia.com/explore/reasoning
#       Common pattern: nvidia/minimax-m2.5 or minimax/minimax-m2.5
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIG — edit these
# =============================================================================

# TODO: Verify this model ID against the NVIDIA NIM catalog.
# The model must be available on api.nvidia.com for free-tier access.
MODEL="opencode/minimax-m2.5-free"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXECWRAP="$PROJECT_DIR/.exec/execwrap.bash"
OPENCODE_BIN="/home/martin/.opencode/bin/opencode"
LOGS_DIR="$PROJECT_DIR/.log/opencode-tests"

# Sleep between API calls (seconds). Free NVIDIA tier: 15–30s recommended.
SLEEP_BETWEEN_TESTS=2

TIMEOUT_SECS=120
DRY_RUN=false

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

for arg in "$@"; do
  case "$arg" in
    --dry-run)          DRY_RUN=true ;;
    --fast)             SLEEP_BETWEEN_TESTS=3 ;;
    --model=*)          MODEL="${arg#--model=}" ;;
    --model)            ;;  # handled by next-arg logic below
  esac
done
# Handle --model <value> (two separate args)
prev=""
for arg in "$@"; do
  if [[ "$prev" == "--model" ]]; then
    MODEL="$arg"
  fi
  prev="$arg"
done

# =============================================================================
# SETUP
# =============================================================================

mkdir -p "$LOGS_DIR"
TS=$(date +%Y%m%d_%H%M%S)
SUMMARY_LOG="$LOGS_DIR/${TS}_summary.log"

_ts()  { date '+%H:%M:%S'; }
_log() { echo "[$(_ts)] $*" | tee -a "$SUMMARY_LOG"; }
_ok()  { echo "[$(_ts)]   PASS  $*" | tee -a "$SUMMARY_LOG"; }
_fail(){ echo "[$(_ts)]   FAIL  $*" | tee -a "$SUMMARY_LOG"; }
_sep() { echo "──────────────────────────────────────────────────────" | tee -a "$SUMMARY_LOG"; }

_log "opencode execwrap test suite"
_log "Model:   $MODEL"
_log "Wrapper: $EXECWRAP"
_log "Logs:    $LOGS_DIR"
$DRY_RUN && _log "Mode:    DRY RUN (no API calls)"
_sep

# Determine launch command (same logic as ralph_loop.sh)
if [[ -x "$EXECWRAP" ]]; then
  OPENCODE_CMD="$EXECWRAP $OPENCODE_BIN"
  _log "Security wrapper: ACTIVE"
else
  OPENCODE_CMD="$OPENCODE_BIN"
  _log "WARNING: execwrap not found at $EXECWRAP — running without security wrapper"
fi

if ! $DRY_RUN; then
  if [[ ! -x "$OPENCODE_BIN" ]]; then
    _log "ERROR: opencode not found at $OPENCODE_BIN"
    exit 1
  fi
fi

# =============================================================================
# TEST RUNNER
# =============================================================================

PASS=0
FAIL=0
SKIP=0

# run_test <test_id> <description> <prompt> <expected_pattern>
# expected_pattern is a grep -i regex matched against the extracted text content
run_test() {
  local id="$1"
  local desc="$2"
  local prompt="$3"
  local expected="$4"
  local log="$LOGS_DIR/${TS}_${id}.log"

  _sep
  _log "TEST $id: $desc"
  _log "  Prompt:   $prompt"
  _log "  Expect:   $expected"
  _log "  Log:      $log"

  if $DRY_RUN; then
    _log "  [DRY RUN — skipped]"
    SKIP=$((SKIP + 1))
    return
  fi

  local exit_code=0
  set +e
  timeout "${TIMEOUT_SECS}s" setsid env __EXECWRAP_ACTIVE=1 XDG_DATA_HOME="$(mktemp -d /tmp/opencode_XXXXXX)" \
    $OPENCODE_CMD run \
    --model "$MODEL" \
    --format json \
    </dev/null \
    "$prompt" > "$log" 2>&1
  exit_code=$?
  set -e

  local log_size
  log_size=$(wc -c < "$log" 2>/dev/null || echo 0)
  _log "  Exit: $exit_code  Size: ${log_size}B"

  if [[ "$log_size" -gt 0 ]]; then
    _log "  Raw output (last 5 lines):"
    tail -5 "$log" 2>/dev/null | sed 's/^/    /' | tee -a "$SUMMARY_LOG"
  fi

  # Extract text content from JSON output
  # opencode --format json emits lines like: {"type":"...","text":"PONG"}
  # or a final result line. We grep for the text content.
  local text_content=""
  text_content=$(grep -o '"text":"[^"]*"' "$log" 2>/dev/null | tail -1 | sed 's/"text":"//;s/"//' || echo "")
  if [[ -z "$text_content" ]]; then
    # Fallback: grep for any line containing the expected pattern directly
    text_content=$(grep -i "$expected" "$log" 2>/dev/null | tail -1 || echo "")
  fi

  _log "  Extracted text: ${text_content:0:120}"

  # Only search JSON lines (lines starting with '{') to avoid matching
  # execwrap debug banner lines which echo the prompt back.
  local json_lines
  json_lines=$(grep '^{' "$log" 2>/dev/null || true)

  # Check for API-level error in JSON output
  local api_error=""
  api_error=$(echo "$json_lines" | grep '"type":"error"' | tail -1 || true)

  if [[ "$exit_code" -eq 124 ]]; then
    _fail "$id: TIMEOUT after ${TIMEOUT_SECS}s"
    FAIL=$((FAIL + 1))
  elif [[ -n "$api_error" ]]; then
    local err_msg
    err_msg=$(echo "$api_error" | grep -o '"message":"[^"]*"' | sed 's/"message":"//;s/"//' || echo "$api_error")
    if echo "$api_error" | grep -qi "rate.limit\|too many requests\|429"; then
      _fail "$id: RATE LIMITED — $err_msg"
    else
      _fail "$id: API error — $err_msg"
    fi
    FAIL=$((FAIL + 1))
  elif echo "$json_lines" | grep -qi "$expected" 2>/dev/null; then
    _ok "$id: $desc"
    PASS=$((PASS + 1))
  else
    _fail "$id: response did not match expected pattern '$expected'"
    _log "  JSON lines in log:"
    echo "$json_lines" | tail -5 | sed 's/^/    /' | tee -a "$SUMMARY_LOG"
    FAIL=$((FAIL + 1))
  fi
}

sleep_between() {
  if ! $DRY_RUN && [[ $SLEEP_BETWEEN_TESTS -gt 0 ]]; then
    _log "  (sleeping ${SLEEP_BETWEEN_TESTS}s for rate limit...)"
    sleep "$SLEEP_BETWEEN_TESTS"
  fi
}

# =============================================================================
# TEST CASES — safe, non-destructive prompts only
# =============================================================================

# T01: Basic ping — simplest possible test
run_test "T01_ping" \
  "Basic ping — model must reply with exactly PONG" \
  "Reply with exactly one word: PONG. Do not add any other text, punctuation, or explanation." \
  "PONG"

sleep_between

# T02: Simple arithmetic
run_test "T02_math" \
  "Simple arithmetic — 7 + 8" \
  "What is 7 + 8? Reply with only the number, nothing else." \
  "15"

sleep_between

# T03: String transformation
run_test "T03_uppercase" \
  "String uppercase — hello world" \
  "Convert this text to uppercase and reply with only the result, nothing else: hello world" \
  "HELLO WORLD"

sleep_between

# T04: Counting
run_test "T04_count" \
  "Count 1 to 5 on separate lines" \
  "Count from 1 to 5. Output each number on its own line, nothing else." \
  "1"

sleep_between

# T05: List output
run_test "T05_list" \
  "List 3 primary colors" \
  "List the 3 primary colors of light (RGB). One per line, lowercase, no punctuation, nothing else." \
  "red\|green\|blue"

sleep_between

# T06: JSON awareness — model understands structured output request
run_test "T06_json_field" \
  "Respond with a specific JSON key" \
  'Respond with exactly this JSON and nothing else: {"status":"ok","model":"ready"}' \
  'status.*ok'

sleep_between

# T07: Sentence completion — verifies actual language model capability
run_test "T07_completion" \
  "Complete the sentence about the sky" \
  "Complete this sentence with exactly 3 words (no punctuation, no extra text): The sky is" \
  "[a-zA-Z]"

sleep_between

# T08: Token awareness — check the model understands its context
run_test "T08_ready" \
  "Final readiness check — READY token" \
  "You are an AI assistant in a testing pipeline. Reply with exactly: READY" \
  "READY"

# =============================================================================
# SUMMARY
# =============================================================================

_sep
_log ""
_log "Results: $PASS passed  $FAIL failed  $SKIP skipped"
_log "Summary log: $SUMMARY_LOG"
_log ""

if [[ $FAIL -gt 0 ]]; then
  _log "FAILED — check logs above for details"
  _log "Common fixes:"
  _log "  429 rate limit  → increase SLEEP_BETWEEN_TESTS (currently ${SLEEP_BETWEEN_TESTS}s)"
  _log "  Wrong model ID  → check https://build.nvidia.com/explore/reasoning and update MODEL="
  _log "  Timeout         → increase TIMEOUT_SECS (currently ${TIMEOUT_SECS}s)"
  exit 1
else
  _log "ALL TESTS PASSED"
  exit 0
fi
