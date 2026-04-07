#!/usr/bin/env bash
# =============================================================================
# ralph_loop.sh — Generic Autonomous Research / Engineering Loop
# =============================================================================
#
# A Ralph-pattern loop for iteratively making progress on a research or
# engineering goal using AI subagents. Adapted from the Lean sorry-elimination
# loop in the riemann2 project.
#
# TODO: Adapt for your project:
#   1. Set PROJECT_DIR / WORK_DIR to your project root
#   2. Set LOOP_DIR to where tasks.md, progress.md, plan.md live
#   3. Set PROMPTS_DIR to where your step prompt templates live
#   4. Edit quality_gate() to run your project's build/test command
#   5. Edit the completion check at the end of the main loop
#   6. Edit build_prompt() context header with your project's key locations
#   7. Tune TIMEOUT_* for your project's step durations
#
# Usage:
#   ./scripts/ralph_loop.sh [OPTIONS] [BUDGET]
#
# Options:
#   --dry-run     Validate setup without running
#   --resume      Resume from last cycle
#   --fresh       Start fresh (backs up old state)
#   --verbose     Print debug info
#   --model MODEL        Use specific model for execute/critic (default: claude-haiku-4-5-20251001)
#   --model-light MODEL  Use specific model for orient/finalize (default: claude-haiku-4-5-20251001)
#                        Models starting with nvidia/ are run via opencode; others via claude CLI.
#   BUDGET        Max cycles (default: 10)
#
# Run from a REGULAR terminal, NOT from inside Claude Code.
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

# TODO: Set PROJECT_DIR to your project root.
# Current default: parent of the directory containing this script.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# TODO: Set WORK_DIR to the main working directory for the loop
# (e.g. the formalization dir, the src dir, etc.)
WORK_DIR="$PROJECT_DIR"

# TODO: Set LOOP_DIR to where tasks.md, progress.md, plan.md, prompts/ live.
# In riemann2 this was schaunelconditional/ralph/
LOOP_DIR="$PROJECT_DIR/ralph"

TASKS="$LOOP_DIR/tasks.md"
PROGRESS="$LOOP_DIR/progress.md"
PLAN="$LOOP_DIR/plan.md"
STEPS_DIR="$LOOP_DIR/steps"
LOGS_DIR="$LOOP_DIR/logs"
PROMPTS_DIR="$LOOP_DIR/prompts"
CYCLE_FILE="$LOOP_DIR/cycle_count.txt"
EXECWRAP="$PROJECT_DIR/.exec/execwrap.bash"

# Defaults
BUDGET=10
DRY_RUN=false
RESUME=false
FRESH=false
VERBOSE=true  # default: verbose on
MODEL_EXECUTE="opencode/minimax-m2.5-free"     # execute model (via opencode)
MODEL_LIGHT="claude-haiku-4-5-20251001"        # orient/plan/critic/finalize via claude CLI (fast + cheap)
ENGINE_EXECUTE="opencode"                      # engine for execute step: "opencode" or "claude"
OPENCODE_BIN="/home/martin/.opencode/bin/opencode"

# Step timeouts (minutes)
# NOTE: claude -p buffers output — on timeout, ALL output is lost.
# Set generous timeouts. Orient/plan/critic are text-only (fast).
# TODO: Tune these for your project. Execute needs time for builds + AI work.
TIMEOUT_ORIENT=20
TIMEOUT_PLAN=20
TIMEOUT_EXECUTE=120
TIMEOUT_CRITIC=45
TIMEOUT_FINALIZE=30

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=true ;;
    --resume)         RESUME=true ;;
    --fresh)          FRESH=true ;;
    --quiet)          VERBOSE=false ;;
    --model=*)        MODEL="${arg#--model=}" ;;
    --model-light=*)  MODEL_LIGHT="${arg#--model-light=}" ;;
    [0-9]*)           BUDGET="$arg" ;;
  esac
done

# =============================================================================
# UTILITIES
# =============================================================================

mkdir -p "$LOGS_DIR" 2>/dev/null || true
MASTER_LOG="$LOGS_DIR/ralph_loop_$(date +%Y%m%d_%H%M%S).log"
touch "$MASTER_LOG" 2>/dev/null || true

_log() {
  local msg="[$(_ts)] [ralph-loop] $*"
  echo "$msg"
  echo "$msg" >> "$MASTER_LOG" 2>/dev/null || true
}

_debug() {
  if $VERBOSE; then
    local msg="[$(_ts)] [ralph-loop:debug] $*"
    echo "$msg"
    echo "$msg" >> "$MASTER_LOG" 2>/dev/null || true
  fi
}

_ts() { date '+%Y-%m-%d %H:%M:%S'; }

# =============================================================================
# PREREQUISITES
# =============================================================================

# TODO: Update this header line for your project
_log "Generic Ralph Loop — Autonomous Research / Engineering"
_log "======================================================="
_log "Project:   $PROJECT_DIR"
_log "Work dir:  $WORK_DIR"
_log "Model:     $MODEL_EXECUTE [$ENGINE_EXECUTE] (execute) | $MODEL_LIGHT [claude] (orient/plan/critic/finalize)"
_log "Budget:    $BUDGET cycles"
echo ""

# Check files exist
for f in "$TASKS" "$PROGRESS" "$PLAN"; do
  if [[ ! -f "$f" ]]; then
    _log "ERROR: Required file not found: $f"
    exit 1
  fi
done

mkdir -p "$STEPS_DIR" "$LOGS_DIR"

# Check claude CLI and execwrap (unless dry-run)
if ! $DRY_RUN; then
  if ! command -v claude &>/dev/null; then
    _log "ERROR: claude CLI not found."
    exit 1
  fi
fi

# Determine launch commands — both claude and opencode go through execwrap
if [[ -x "$EXECWRAP" ]]; then
  CLAUDE_CMD="$EXECWRAP claude"
  OPENCODE_CMD="$EXECWRAP $OPENCODE_BIN"
  _log "Security: execwrap.bash wrapper ACTIVE (claude + opencode)"
else
  CLAUDE_CMD="claude"
  OPENCODE_CMD="$OPENCODE_BIN"
  _log "Security: execwrap.bash NOT FOUND — running without security wrapper"
fi

# =============================================================================
# DRY RUN
# =============================================================================

if $DRY_RUN; then
  _log "=== DRY RUN ==="
  echo ""
  echo "State files:"
  for f in "$TASKS" "$PROGRESS" "$PLAN"; do
    echo "  $(wc -l < "$f") lines  $f"
  done
  echo ""
  echo "Prompts:"
  for f in "$PROMPTS_DIR"/step*.md; do
    echo "  $(wc -c < "$f") bytes  $(basename "$f")"
  done
  echo ""
  echo "Task queue:"
  grep -c '^\- \[ \]' "$TASKS" 2>/dev/null | xargs -I{} echo "  {} pending tasks"
  grep -c '^\- \[x\]' "$TASKS" 2>/dev/null | xargs -I{} echo "  {} completed tasks" || echo "  0 completed tasks"
  echo ""

  # TODO: Replace with your project's quality gate check
  echo "Quality gate (dry run):"
  echo "  TODO: configure quality_gate() for your project"
  echo ""

  echo "Security wrapper:"
  if [[ -x "$EXECWRAP" ]]; then
    echo "  execwrap.bash: ACTIVE"
  else
    echo "  execwrap.bash: not found"
  fi

  # --- Ping tests: one per distinct engine/model combination, using same wrappers as run_subagent() ---
  echo ""
  echo "=== Ping tests (all step engines) ==="
  PING_PROMPT="Reply with exactly: PONG"
  PING_ALL_OK=true

  ping_one() {
    local label="$1"
    local engine="$2"    # "opencode" or "claude"
    local model="$3"
    local log="$LOGS_DIR/ping_${label}_$$.log"

    printf "  %-35s" "[$label] $engine / $model"
    set +e
    if [[ "$engine" == "opencode" ]]; then
      timeout 240s setsid env __EXECWRAP_ACTIVE=1 XDG_DATA_HOME="$(mktemp -d /tmp/opencode_XXXXXX)" \
        $OPENCODE_CMD run \
        --model "$model" \
        --format json \
        </dev/null \
        "$PING_PROMPT" > "$log" 2>&1
    else
      timeout 90s env -u CLAUDECODE __EXECWRAP_ACTIVE=1 \
        $CLAUDE_CMD \
        --model "$model" \
        --dangerously-skip-permissions \
        --allowedTools "Read" \
        -p "$PING_PROMPT" \
        </dev/null > "$log" 2>&1
    fi
    local exit_code=$?
    set -e
    local log_size=$(wc -c < "$log" 2>/dev/null || echo 0)
    # opencode outputs JSON with "text":"PONG"; claude outputs plain text PONG
    if grep -qi '"text".*PONG\|^PONG' "$log" 2>/dev/null; then
      echo "  OK (exit=$exit_code, ${log_size}B)"
    else
      echo "  FAILED (exit=$exit_code, ${log_size}B)"
      echo "    Last 10 lines:"
      tail -10 "$log" 2>/dev/null | sed 's/^/      /' || echo "      (empty)"
      PING_ALL_OK=false
    fi
    rm -f "$log"
  }

  # Derive engine from model prefix — same logic as run_subagent()
  _engine() { [[ "$1" == nvidia/* ]] && echo "opencode" || echo "claude"; }

  # Step 1/4: orient + finalize
  ping_one "orient+finalize" "$(_engine "$MODEL_LIGHT")" "$MODEL_LIGHT"

  # Step 2: plan — always claude + haiku
  ping_one "plan" "claude" "claude-haiku-4-5-20251001"

  # Step 3: execute — engine forced by ENGINE_EXECUTE, model from MODEL_EXECUTE
  ping_one "execute" "$ENGINE_EXECUTE" "$MODEL_EXECUTE"

  # Step 3c: critic — always claude + haiku
  ping_one "critic" "claude" "claude-haiku-4-5-20251001"

  echo ""
  if $PING_ALL_OK; then
    _log "All ping tests PASSED. No state files were modified."
  else
    _log "One or more ping tests FAILED. Review output above."
  fi
  echo ""
  _log "Dry run complete. To run:"
  _log "  ./scripts/ralph_loop.sh $BUDGET"
  exit 0
fi

# =============================================================================
# RESUME / FRESH DETECTION
# =============================================================================

START_CYCLE=1

if [[ -f "$CYCLE_FILE" ]]; then
  LAST_CYCLE=$(cat "$CYCLE_FILE" 2>/dev/null || echo "0")
  # Trim whitespace
  LAST_CYCLE=$(echo "$LAST_CYCLE" | tr -d '[:space:]')
else
  LAST_CYCLE=0
fi

if [[ $LAST_CYCLE -gt 0 ]] && ! $RESUME && ! $FRESH; then
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  Previous run detected: $LAST_CYCLE cycles completed              ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "Last progress entries:"
  grep "^## Cycle" "$PROGRESS" 2>/dev/null | tail -3 | sed 's/^/  /' || echo "  (no cycle entries yet)"
  echo ""

  read -p "Resume from cycle $((LAST_CYCLE + 1))? [Y/n] " -n 1 -r
  echo ""
  if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    START_CYCLE=$((LAST_CYCLE + 1))
    _log "Resuming from cycle $START_CYCLE"
  else
    read -p "Start FRESH (backs up old state)? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      BACKUP="$LOOP_DIR/backups/$(date +%Y%m%d_%H%M%S)"
      mkdir -p "$BACKUP"
      cp "$TASKS" "$PROGRESS" "$PLAN" "$BACKUP/" 2>/dev/null || true
      cp "$CYCLE_FILE" "$BACKUP/" 2>/dev/null || true
      _log "Backed up to: $BACKUP"
      START_CYCLE=1
      echo "0" > "$CYCLE_FILE"
    else
      _log "Cancelled."
      exit 0
    fi
  fi
elif $RESUME; then
  START_CYCLE=$((LAST_CYCLE + 1))
  _log "Resuming from cycle $START_CYCLE"
elif $FRESH && [[ $LAST_CYCLE -gt 0 ]]; then
  BACKUP="$LOOP_DIR/backups/$(date +%Y%m%d_%H%M%S)"
  mkdir -p "$BACKUP"
  cp "$TASKS" "$PROGRESS" "$PLAN" "$BACKUP/" 2>/dev/null || true
  _log "Backed up to: $BACKUP"
  START_CYCLE=1
  echo "0" > "$CYCLE_FILE"
fi

# =============================================================================
# SUBAGENT RUNNER
# =============================================================================

run_subagent() {
  local step_name="$1"
  local prompt_file="$2"
  local timeout_min="$3"
  local step_model="${4:-$MODEL}"
  local step_engine="${5:-auto}"   # "auto" (nvidia/* → opencode, else → claude), "opencode", or "claude"
  local step_tools="${6:-Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch,Task}"
  local output_log="$LOGS_DIR/$(date +%Y%m%d_%H%M%S)_${step_name}.log"
  local max_hang_retries=2
  local attempt=0

  _log ""
  _log "┌─────────────────────────────────────────────────────┐"
  _log "│ STEP: $step_name"
  _log "├─────────────────────────────────────────────────────┤"
  _log "│ Timeout:  ${timeout_min}m"
  _log "│ Model:    $step_model"
  _log "│ Engine:   $step_engine"
  _log "│ Prompt:   $prompt_file ($(wc -c < "$prompt_file" 2>/dev/null || echo '?') bytes)"
  _log "│ Log:      $output_log"
  _log "│ Monitor:  tail -f $output_log"
  _log "└─────────────────────────────────────────────────────┘"
  _log ""

  while [[ $attempt -lt $((max_hang_retries + 1)) ]]; do
    # Heartbeat watcher (background)
    local cur_log="$output_log"
    (
      hb_prev=0; hb_mins=0
      while true; do
        sleep 300  # every 5 minutes
        hb_mins=$((hb_mins + 5))
        hb_cur=$(wc -c < "$cur_log" 2>/dev/null || echo 0)
        if [[ "$hb_cur" -le "$hb_prev" ]]; then
          printf "  [heartbeat %dm] no new output — log: %dB\n" "$hb_mins" "$hb_cur"
        else
          printf "  [heartbeat %dm] running — log: %dB (+%dB)\n" "$hb_mins" "$hb_cur" "$((hb_cur - hb_prev))"
        fi
        hb_prev=$hb_cur
      done
    ) &
    local heartbeat_pid=$!

    # Run the subagent — dispatch based on step_engine / model prefix:
    #   step_engine=opencode  → opencode run (execwrap, setsid, --format json)
    #   step_engine=claude    → claude --print (prompt via stdin, no ARG_MAX limit)
    #   step_engine=auto      → nvidia/* model prefix → opencode, else → claude
    # __EXECWRAP_ACTIVE=1 prevents guard.sh self-triggering on the claude path.
    #
    # NOTE: Do NOT use -p "$prompt_text" for claude — loading large prompts into a shell
    # variable and passing as a CLI arg hits ARG_MAX (E2BIG). Use --print with stdin
    # redirect instead; the default --input-format text reads the prompt from stdin.
    local use_opencode=false
    if [[ "$step_engine" == "opencode" ]] || { [[ "$step_engine" == "auto" ]] && [[ "$step_model" == nvidia/* ]]; }; then
      use_opencode=true
    fi
    set +e
    if $use_opencode; then
      # opencode path — through execwrap, setsid for process group isolation
      # TODO: When adapting for opencode, ensure PATH is set correctly for tools
      # (e.g. export PATH="$HOME/.elan/bin:$PATH" for Lean projects) inside prompts
      local prompt_text
      prompt_text="$(cat "$prompt_file")"
      _debug "[$step_name] Using opencode engine (engine=$step_engine) for model: $step_model"
      timeout "${timeout_min}m" setsid env __EXECWRAP_ACTIVE=1 XDG_DATA_HOME="$(mktemp -d /tmp/opencode_XXXXXX)" \
        $OPENCODE_CMD run \
        --model "$step_model" \
        --format json \
        </dev/null \
        "$prompt_text" > "$output_log" 2>&1
    else
      # claude path — security wrapper + permission flags; prompt via stdin (no ARG_MAX)
      _debug "[$step_name] Using claude engine (engine=$step_engine) for model: $step_model"
      timeout "${timeout_min}m" env -u CLAUDECODE __EXECWRAP_ACTIVE=1 \
        $CLAUDE_CMD \
        --model "$step_model" \
        --dangerously-skip-permissions \
        --allowedTools "$step_tools" \
        --print \
        < "$prompt_file" > "$output_log" 2>&1
    fi
    local exit_code=$?
    set -e

    # Show output for monitoring — opencode emits JSON event stream; extract text only
    if [[ -f "$output_log" ]]; then
      local log_size_now
      log_size_now=$(wc -c < "$output_log" 2>/dev/null || echo 0)
      _log "[$step_name] Completed — ${log_size_now}B output (exit code: $exit_code)"
      if $VERBOSE && [[ "$log_size_now" -gt 0 ]]; then
        if $use_opencode; then
          # opencode: extract text fields from JSON event stream, skip execwrap banners
          local text_out
          text_out=$(grep '^{' "$output_log" 2>/dev/null \
            | grep '"type":"text"' \
            | grep -o '"text":"[^"]*"' \
            | sed 's/"text":"//;s/"$//' \
            | tr -d '\n' \
            | head -c 500 || true)
          if [[ -n "$text_out" ]]; then
            _log "[$step_name] Response: $text_out"
          else
            # No text events — show last JSON line (likely an error)
            grep '^{' "$output_log" 2>/dev/null | tail -1 | head -c 300 || true
          fi
        else
          tail -20 "$output_log" 2>/dev/null || true
        fi
      fi
    fi

    # Kill heartbeat
    kill "$heartbeat_pid" 2>/dev/null || true
    wait "$heartbeat_pid" 2>/dev/null || true

    # Check for timeout with no output (API hang — Lesson 34)
    if [[ "$exit_code" -eq 124 ]]; then
      local log_size
      log_size=$(wc -c < "$output_log" 2>/dev/null || echo 0)
      if [[ "$log_size" -lt 2000 ]]; then
        attempt=$((attempt + 1))
        if [[ $attempt -le $max_hang_retries ]]; then
          _log "[$step_name] API hang detected (exit 124, ${log_size}B). Retry $attempt/$max_hang_retries..."
          sleep 15
          output_log="$LOGS_DIR/$(date +%Y%m%d_%H%M%S)_${step_name}_retry${attempt}.log"
          continue
        fi
      else
        _log "[$step_name] Genuine timeout (${log_size}B output). Not retrying."
      fi
    fi

    # Done
    local log_size
    log_size=$(wc -c < "$output_log" 2>/dev/null || echo 0)

    if [[ "$exit_code" -ne 0 ]]; then
      # Check for rate limit only on failure — a successful step may mention "429"
      # in passing (e.g. opencode retried internally), and we must not waste 10 min on that.
      if grep -qi "rate.limit\|hit your limit\|too many requests\|429" "$output_log" 2>/dev/null; then
        _log "[$step_name] Rate limit detected (exit $exit_code). Waiting 10 minutes..."
        sleep 600
        attempt=$((attempt + 1))
        if [[ $attempt -le $max_hang_retries ]]; then
          output_log="$LOGS_DIR/$(date +%Y%m%d_%H%M%S)_${step_name}_ratelimit${attempt}.log"
          continue
        fi
      fi
      _log "[$step_name] FAILED (exit $exit_code, ${log_size}B)"
      tail -10 "$output_log" 2>/dev/null | sed 's/^/  /' || true
      return "$exit_code"
    fi

    _log "[$step_name] COMPLETED (${log_size}B)"
    return 0
  done

  _log "[$step_name] Failed after $max_hang_retries retries"
  return 1
}

# =============================================================================
# BUILD STEP PROMPTS
# =============================================================================

# =============================================================================
# ORIENT CONTEXT PRE-PROCESSOR
# Pre-digests large state files so the orient model only sees relevant content.
# tasks.md may have many completed tasks; we only inject the pending ones.
# progress.md may have many cycle entries; we only inject the last 5.
# (Lesson 44: pre-digest state files before orient, bash not LLM, ~11x compression)
# =============================================================================

build_orient_context() {
  local output="$STEPS_DIR/orient_context.md"

  {
    echo "# Pre-Digested State Context (auto-generated by ralph_loop.sh)"
    echo ""
    echo "> tasks.md has $(wc -l < "$TASKS") lines total; only pending tasks and"
    echo "> current-state header shown below. progress.md has $(wc -l < "$PROGRESS")"
    echo "> lines total; only last 5 cycles shown. Do NOT re-read these full files."
    echo ""

    # ── tasks.md: header + current state (~80 lines) ────────────────────────
    echo "## Tasks — Header and Current State (tasks.md lines 1–80)"
    echo ""
    head -80 "$TASKS"
    echo ""
    echo "---"
    echo ""

    # ── tasks.md: each pending task block (compact — 12 lines each) ─────────
    # 35 lines × many tasks = too large; trimmed to 12 lines each.
    echo "## Pending Tasks (all \`- [ ]\` items from tasks.md, compact view)"
    echo ""
    local total_tasks_lines
    total_tasks_lines=$(wc -l < "$TASKS")
    grep -n '^\- \[ \]' "$TASKS" | while IFS=: read -r lineno _; do
      local start end
      start=$((lineno > 2 ? lineno - 2 : 1))
      end=$((lineno + 12))
      [[ $end -gt $total_tasks_lines ]] && end=$total_tasks_lines
      sed -n "${start},${end}p" "$TASKS"
      echo ""
    done

    # ── progress.md: last 3 cycles ──────────────────────────────────────────
    echo "## Recent Progress — Last 3 Cycles (from progress.md)"
    echo "(progress.md has $(wc -l < "$PROGRESS") lines; only last 3 cycles shown)"
    echo ""
    local cycle_start
    cycle_start=$(grep -n '^## Cycle' "$PROGRESS" | tail -3 | head -1 | cut -d: -f1 2>/dev/null || echo "1")
    sed -n "${cycle_start},\$p" "$PROGRESS"
  } > "$output"

  local ctx_size
  ctx_size=$(wc -c < "$output" 2>/dev/null || echo 0)
  local ctx_lines
  ctx_lines=$(wc -l < "$output" 2>/dev/null || echo 0)
  # NOTE: _log writes to stdout — redirect to stderr here so the caller's
  # ctx_file=$(build_orient_context) captures only the file path, not the log line.
  _log "  orient_context.md: ${ctx_lines} lines / ${ctx_size}B (condensed from $(wc -l < "$TASKS") + $(wc -l < "$PROGRESS") lines)" >&2

  echo "$output"
}

build_prompt() {
  local step_name="$1"
  local template="$PROMPTS_DIR/${step_name}.md"
  local output="$STEPS_DIR/${step_name}_prompt.md"

  if [[ ! -f "$template" ]]; then
    _log "ERROR: Template not found: $template"
    return 1
  fi

  # TODO: Update this context header for your project.
  # List key directories and scope restrictions relevant to your work.
  cat > "$output" <<HEADER
# Project Context

Working directory: $PROJECT_DIR
Work directory:    $WORK_DIR
Current cycle: $CURRENT_CYCLE
Date: $(date +%Y-%m-%d)

You have access to the full filesystem. Key locations:
- Project root:    $PROJECT_DIR
- Work directory:  $WORK_DIR
- Loop state:      $LOOP_DIR (tasks.md, progress.md, plan.md)
- Step outputs:    $STEPS_DIR
- TODO: Add your project-specific paths here

CRITICAL SCOPE RESTRICTION:
TODO: Define your project's scope restriction here.
(e.g., "Do NOT modify files outside $WORK_DIR")

---

HEADER

  # For the orient step: inject pre-digested state so the model doesn't need
  # to read the full tasks.md or progress.md files.
  if [[ "$step_name" == "step1_orient" ]]; then
    local ctx_file
    ctx_file=$(build_orient_context)
    echo "" >> "$output"
    echo "---" >> "$output"
    echo "" >> "$output"
    cat "$ctx_file" >> "$output"
    echo "" >> "$output"
    echo "---" >> "$output"
    echo "" >> "$output"
  fi

  cat "$template" >> "$output"
  echo "$output"
}

# =============================================================================
# QUALITY GATE
# =============================================================================

# TODO: Replace this with your project's build/test/quality check.
# For Lean: `cd "$WORK_DIR" && lake build`
# For Python: `cd "$PROJECT_DIR" && uv run pytest`
# For JS/TS: `cd "$PROJECT_DIR" && npm test`
# Should return 0 on pass, non-zero on failure.
quality_gate() {
  _log "QUALITY GATE: TODO — configure for your project"
  _log "  (returning success by default — replace quality_gate() in ralph_loop.sh)"
  # TODO: Replace with real quality gate:
  # if (cd "$WORK_DIR" && your_build_command 2>&1 | tee "$LOGS_DIR/quality_cycle${CURRENT_CYCLE}.log"); then
  #   _log "  QUALITY GATE: PASSED"
  #   return 0
  # else
  #   _log "  QUALITY GATE: FAILED"
  #   return 1
  # fi
  return 0
}

# =============================================================================
# MAIN LOOP
# =============================================================================

_log ""
# TODO: Update this description for your project
_log "Starting loop: cycles $START_CYCLE to $((START_CYCLE + BUDGET - 1))"
_log "=========================================="

# Graceful shutdown
trap '_log "Interrupted — state saved."; echo "$CURRENT_CYCLE" > "$CYCLE_FILE"; exit 130' INT TERM

CURRENT_CYCLE=$START_CYCLE

cycle_count=0
while [[ $cycle_count -lt $BUDGET ]]; do
  cycle_count=$((cycle_count + 1))
  CURRENT_CYCLE=$((START_CYCLE + cycle_count - 1))

  cycle_start_ts=$(date +%s)

  _log ""
  _log "══════════════════════════════════════════════════════════════"
  _log "  CYCLE $CURRENT_CYCLE / $((START_CYCLE + BUDGET - 1))"
  _log "  $(_ts)"
  _log "  Pending tasks: $(grep -c '^\- \[ \]' "$TASKS" 2>/dev/null || echo 0)"
  _log "══════════════════════════════════════════════════════════════"
  _log ""

  # Clean previous step outputs
  rm -f "$STEPS_DIR"/orient.md "$STEPS_DIR"/execute.md "$STEPS_DIR"/finalize.md
  rm -f "$STEPS_DIR"/critic.md

  # ── STEP 1: ORIENT ──────────────────────────────────────────────
  # No Task tool: prevents subagents that bypass --allowedTools and can invoke MCP servers
  _log "Step 1: ORIENT (mechanical summary — model: $MODEL_LIGHT)"
  prompt_file=$(build_prompt "step1_orient")
  if ! run_subagent "orient" "$prompt_file" "$TIMEOUT_ORIENT" "$MODEL_LIGHT" "auto" "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch"; then
    _log "Orient failed — skipping cycle"
    echo "$CURRENT_CYCLE" > "$CYCLE_FILE"
    continue
  fi

  if [[ ! -f "$STEPS_DIR/orient.md" ]]; then
    _log "Orient did not produce orient.md — skipping cycle"
    echo "$CURRENT_CYCLE" > "$CYCLE_FILE"
    continue
  fi

  # ── STEP 2: PLAN (uses Opus for deeper reasoning) ───────────────
  _log "Step 2: PLAN (haiku)"
  prompt_file=$(build_prompt "step2_plan")
  if ! run_subagent "plan" "$prompt_file" "$TIMEOUT_PLAN" "claude-haiku-4-5-20251001"; then
    _log "Plan failed — skipping cycle"
    echo "$CURRENT_CYCLE" > "$CYCLE_FILE"
    continue
  fi

  if ! grep -q "## Selected Task" "$PLAN" 2>/dev/null; then
    _log "Plan step did not produce a valid plan — skipping cycle"
    echo "$CURRENT_CYCLE" > "$CYCLE_FILE"
    continue
  fi

  # ── STEP 3: EXECUTE ─────────────────────────────────────────────
  _log "Step 3: EXECUTE (this may take a while — engine: $ENGINE_EXECUTE model: $MODEL_EXECUTE)"
  prompt_file=$(build_prompt "step3_execute")
  if ! run_subagent "execute" "$prompt_file" "$TIMEOUT_EXECUTE" "$MODEL_EXECUTE" "$ENGINE_EXECUTE"; then
    _log "Execute failed or timed out"
  fi

  # ── QUALITY GATE ─────────────────────────────────────────────────
  quality_gate || _log "  (Quality gate failure — critic will note this)"

  # ── STEP 3c: CRITIC (if substantive work was done) ───────────────
  # TODO: Adapt the grep condition to detect when your project's work was done.
  # Currently looks for any mention of work in execute.md.
  if [[ -f "$STEPS_DIR/execute.md" ]]; then
    if grep -qi "." "$STEPS_DIR/execute.md" 2>/dev/null; then
      _log "Step 3c: CRITIC (haiku via claude — soundness review)"
      prompt_file=$(build_prompt "step3c_critic")
      if run_subagent "critic" "$prompt_file" "$TIMEOUT_CRITIC" "claude-haiku-4-5-20251001"; then
        if [[ -f "$STEPS_DIR/critic.md" ]]; then
          if grep -qi "FLAWED\|FATAL" "$STEPS_DIR/critic.md" 2>/dev/null; then
            _log "  CRITIC FOUND FLAWS — check $STEPS_DIR/critic.md"
          elif grep -qi "CONCERNS" "$STEPS_DIR/critic.md" 2>/dev/null; then
            _log "  Critic raised concerns"
          else
            _log "  Critic: SOUND"
          fi
        fi
      else
        _log "  Critic step failed"
      fi
    fi
  fi

  # ── STEP 4: FINALIZE ────────────────────────────────────────────
  _log "Step 4: FINALIZE (mechanical state update — model: $MODEL_LIGHT)"
  prompt_file=$(build_prompt "step4_finalize")
  if ! run_subagent "finalize" "$prompt_file" "$TIMEOUT_FINALIZE" "$MODEL_LIGHT"; then
    _log "Finalize failed — manually check state files"
  fi

  # Save cycle count
  echo "$CURRENT_CYCLE" > "$CYCLE_FILE"

  # Git commit (best-effort)
  # TODO: Adjust git add scope for your project
  cd "$PROJECT_DIR"
  git add -A 2>/dev/null || true
  git commit -m "ralph-loop cycle $CURRENT_CYCLE: $(head -1 "$PLAN" | sed 's/^# //' 2>/dev/null || echo 'progress')" --no-verify 2>/dev/null || true

  # ── COMPLETION CHECK ─────────────────────────────────────────────
  # TODO: Replace this with your project's completion check.
  # For Lean sorry elimination: check if sorry_count == 0
  # For other projects: check if primary metric threshold is met, all tasks done, etc.
  pending_count=$(grep -c '^\- \[ \]' "$TASKS" 2>/dev/null || echo "?")
  _log ""
  _log "TODO: Add your completion check here (currently just showing pending tasks)"
  _log "  Pending tasks: $pending_count"

  # Example completion check (uncomment and adapt):
  # if [[ "$pending_count" == "0" ]]; then
  #   _log ""
  #   _log "╔══════════════════════════════════════════════════════════════╗"
  #   _log "║  ALL TASKS COMPLETE!                                        ║"
  #   _log "╚══════════════════════════════════════════════════════════════╝"
  #   break
  # fi

  cycle_end_ts=$(date +%s)
  cycle_duration=$(( cycle_end_ts - cycle_start_ts ))
  cycle_min=$(( cycle_duration / 60 ))
  cycle_sec=$(( cycle_duration % 60 ))

  _log "Cycle $CURRENT_CYCLE complete (${cycle_min}m ${cycle_sec}s). Pending tasks: $pending_count"
  _log ""
done

# =============================================================================
# FINAL REPORT
# =============================================================================

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  RALPH LOOP COMPLETE"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "Cycles completed: $cycle_count"
echo "Pending tasks:    $(grep -c '^\- \[ \]' "$TASKS" 2>/dev/null || echo 0)"
echo "Completed tasks:  $(grep -c '^\- \[x\]' "$TASKS" 2>/dev/null || echo 0)"
echo ""

# TODO: Add your project's final quality check here
echo "TODO: Run your project's final quality gate / report here"

echo ""
echo "Review:"
echo "  Tasks:    $TASKS"
echo "  Progress: $PROGRESS"
echo "  Logs:     $LOGS_DIR/"
echo ""
_log "Done."
