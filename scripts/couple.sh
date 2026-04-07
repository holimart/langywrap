#!/usr/bin/env bash
# =============================================================================
# langywrap — Project Coupling Wizard
# =============================================================================
# Couples a downstream project to langywrap for security, ralph loops,
# hyperagent evolution, compound engineering, and quality gates.
#
# Usage:
#   ./scripts/couple.sh /path/to/project            Interactive wizard
#   ./scripts/couple.sh /path/to/project --defaults  Accept defaults
#   ./scripts/couple.sh /path/to/project --minimal   Security only
#   ./scripts/couple.sh /path/to/project --dry-run   Preview changes
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

LANGYWRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
ok()      { echo -e "${GREEN}✓${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
err()     { echo -e "${RED}✗${NC}  $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}\n"; }
step()    { echo -e "${MAGENTA}→${NC} $*"; }

PROJECT_DIR=""
DRY_RUN=false
NON_INTERACTIVE=false
PRESET=""

C_SECURITY=true; C_EXECWRAP=true; C_GIT_HOOKS=true; C_RTK=true
C_RALPH=true; C_HYPERAGENTS=true; C_COMPOUND=true
C_QUALITY=true; C_WRAPPERS=true; C_DEV_DEP=true

ask_yn() {
    local prompt="$1" default="${2:-y}"
    if $NON_INTERACTIVE; then [[ "$default" == "y" ]] && return 0 || return 1; fi
    local yn
    if [[ "$default" == "y" ]]; then
        read -rp "$(echo -e "${BOLD}$prompt${NC} [Y/n] ")" yn
        [[ -z "$yn" || "$yn" =~ ^[Yy] ]]
    else
        read -rp "$(echo -e "${BOLD}$prompt${NC} [y/N] ")" yn
        [[ "$yn" =~ ^[Yy] ]]
    fi
}

for arg in "$@"; do
    case "$arg" in
        --dry-run)    DRY_RUN=true ;;
        --defaults)   NON_INTERACTIVE=true ;;
        --minimal)    NON_INTERACTIVE=true; PRESET="minimal" ;;
        --full)       NON_INTERACTIVE=true; PRESET="full" ;;
        --help|-h)
            echo "Usage: couple.sh /path/to/project [OPTIONS]"
            echo "  --defaults   Accept all defaults"
            echo "  --minimal    Security hooks + git hooks only"
            echo "  --full       Everything (default)"
            echo "  --dry-run    Preview changes"
            exit 0 ;;
        -*) err "Unknown option: $arg"; exit 1 ;;
        *)  PROJECT_DIR="$arg" ;;
    esac
done

if [[ -z "$PROJECT_DIR" ]]; then err "Usage: couple.sh /path/to/project [OPTIONS]"; exit 1; fi
PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd || echo "$PROJECT_DIR")"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
[[ ! -d "$PROJECT_DIR" ]] && { err "Not found: $PROJECT_DIR"; exit 1; }

[[ "$PRESET" == "minimal" ]] && {
    C_RALPH=false; C_HYPERAGENTS=false; C_COMPOUND=false
    C_QUALITY=false; C_WRAPPERS=false; C_DEV_DEP=false; C_RTK=false
}

coupling_wizard() {
    header "Coupling $PROJECT_NAME to langywrap"
    echo -e "Select features for ${BOLD}$PROJECT_DIR${NC}:\n"
    echo -e "${BOLD}Security:${NC}"
    echo -e "  1) Security hooks  — Block dangerous commands in Claude/OpenCode/Cursor"
    echo -e "  2) ExecWrap        — 5-layer execution wrapper"
    echo -e "  3) Git hooks       — Pre-commit scan + force-push block"
    echo -e "  4) RTK             — Output compression for token savings"
    echo -e "${BOLD}AI Agent:${NC}"
    echo -e "  5) Ralph loop      — Autonomous loop state directory + prompts"
    echo -e "  6) HyperAgents     — Link to evolution archive + router config"
    echo -e "  7) Compound eng.   — docs/solutions/ + knowledge flow to hub"
    echo -e "${BOLD}Development:${NC}"
    echo -e "  8) Quality gates   — Compact output config check"
    echo -e "  9) Wrappers        — ./just and ./uv pager wrappers"
    echo -e " 10) Dev dependency  — Add langywrap as editable dev dep"
    echo ""
    ask_yn "  1) Security hooks?" "y" && C_SECURITY=true || C_SECURITY=false
    ask_yn "  2) ExecWrap?" "y" && C_EXECWRAP=true || C_EXECWRAP=false
    ask_yn "  3) Git hooks?" "y" && C_GIT_HOOKS=true || C_GIT_HOOKS=false
    ask_yn "  4) RTK compression?" "y" && C_RTK=true || C_RTK=false
    ask_yn "  5) Ralph loop?" "y" && C_RALPH=true || C_RALPH=false
    ask_yn "  6) HyperAgents?" "y" && C_HYPERAGENTS=true || C_HYPERAGENTS=false
    ask_yn "  7) Compound eng.?" "y" && C_COMPOUND=true || C_COMPOUND=false
    ask_yn "  8) Quality gates?" "y" && C_QUALITY=true || C_QUALITY=false
    ask_yn "  9) Wrappers?" "y" && C_WRAPPERS=true || C_WRAPPERS=false
    ask_yn " 10) Dev dependency?" "y" && C_DEV_DEP=true || C_DEV_DEP=false
    echo ""
}

# --- Coupling steps ---
couple_config() {
    step "Creating .langywrap/ config..."
    $DRY_RUN && { info "[dry-run] mkdir .langywrap/"; return; }
    mkdir -p "$PROJECT_DIR/.langywrap"
    cat > "$PROJECT_DIR/.langywrap/config.yaml" << EOF
project_name: "$PROJECT_NAME"
langywrap_dir: "$LANGYWRAP_DIR"
archive_dir: "$LANGYWRAP_DIR/experiments/archive"
hub_solutions_dir: "$LANGYWRAP_DIR/docs/solutions"
EOF
    ok ".langywrap/config.yaml"
}

couple_security() {
    $C_SECURITY || return 0
    step "Installing security hooks..."
    $DRY_RUN && { info "[dry-run] install hooks"; return; }
    mkdir -p "$PROJECT_DIR/.claude/hooks"
    for hook in security_hook.sh agent_research_opencode.sh websearch_kimi.sh; do
        [[ -f "$LANGYWRAP_DIR/hooks/claude/$hook" ]] || continue
        sed "s/__PROJECT_NAME__/$PROJECT_NAME/g" "$LANGYWRAP_DIR/hooks/claude/$hook" \
            > "$PROJECT_DIR/.claude/hooks/$hook"
        chmod +x "$PROJECT_DIR/.claude/hooks/$hook"
    done
    mkdir -p "$PROJECT_DIR/.opencode/plugins"
    cp "$LANGYWRAP_DIR/hooks/opencode/security-guard.ts" "$PROJECT_DIR/.opencode/plugins/" 2>/dev/null || true
    ok "Security hooks installed"
}

couple_execwrap() {
    $C_EXECWRAP || return 0
    step "Installing ExecWrap..."
    $DRY_RUN && { info "[dry-run] copy .exec/"; return; }
    mkdir -p "$PROJECT_DIR/.exec"

    # Symlink execwrap.bash so updates propagate; copy config files (they diverge per-project)
    local src="$LANGYWRAP_DIR/execwrap"
    for f in execwrap.bash preload.sh; do
        ln -sf "$src/$f" "$PROJECT_DIR/.exec/$f"
    done
    # Copy settings.json only if it doesn't exist (preserve project customizations)
    [[ -f "$PROJECT_DIR/.exec/settings.json" ]] || cp "$src/settings.json" "$PROJECT_DIR/.exec/"
    [[ -f "$src/README.md" ]] && cp "$src/README.md" "$PROJECT_DIR/.exec/" 2>/dev/null || true
    chmod +x "$PROJECT_DIR/.exec/execwrap.bash" "$PROJECT_DIR/.exec/preload.sh" 2>/dev/null || true

    # Copy RTK binary if available
    if [[ -x "$LANGYWRAP_DIR/.exec/rtk" ]]; then
        cp "$LANGYWRAP_DIR/.exec/rtk" "$PROJECT_DIR/.exec/rtk"
        chmod +x "$PROJECT_DIR/.exec/rtk"
        ok "RTK binary at .exec/rtk"
    fi

    ok "ExecWrap at .exec/ (symlinked — updates propagate)"
}

couple_git_hooks() {
    $C_GIT_HOOKS || return 0
    step "Installing git hooks..."
    $DRY_RUN && { info "[dry-run] .githooks/"; return; }
    mkdir -p "$PROJECT_DIR/.githooks"
    cp "$LANGYWRAP_DIR/hooks/githooks/"* "$PROJECT_DIR/.githooks/"
    chmod +x "$PROJECT_DIR/.githooks/"*
    [[ -d "$PROJECT_DIR/.git" ]] && git -C "$PROJECT_DIR" config core.hooksPath .githooks
    ok "Git hooks installed"
}

couple_ralph() {
    $C_RALPH || return 0
    step "Setting up ralph loop..."
    $DRY_RUN && { info "[dry-run] research/ralph/"; return; }
    local rd="$PROJECT_DIR/research/ralph"
    mkdir -p "$rd/prompts" "$rd/steps" "$rd/logs"
    cp "$LANGYWRAP_DIR/lib/langywrap/ralph/prompts/"*.md "$rd/prompts/" 2>/dev/null || true
    [[ -f "$rd/cycle_count.txt" ]] || echo "0" > "$rd/cycle_count.txt"
    [[ -f "$rd/tasks.md" ]] || echo "# Tasks" > "$rd/tasks.md"
    [[ -f "$rd/progress.md" ]] || echo "# Progress" > "$rd/progress.md"
    cat > "$PROJECT_DIR/.langywrap/ralph.yaml" << EOF
project_dir: "$PROJECT_DIR"
state_dir: "research/ralph"
budget: 50
review_every_n: 10
git_commit_after_cycle: true
git_add_paths: ["src/", "tests/", "scripts/", "research/"]
quality_gate: {command: "./just check", timeout_minutes: 10, required: true}
EOF
    ok "Ralph loop at research/ralph/"
}

couple_hyperagents() {
    $C_HYPERAGENTS || return 0
    step "Configuring HyperAgent routing..."
    $DRY_RUN && { info "[dry-run] router.yaml"; return; }
    cat > "$PROJECT_DIR/.langywrap/router.yaml" << 'EOF'
name: default
review_every_n: 10
rules:
  - {role: orient, model: claude-haiku-4-5-20251001, backend: claude, timeout_minutes: 20}
  - {role: plan, model: claude-sonnet-4-6, backend: claude, timeout_minutes: 20}
  - {role: execute, model: nvidia/moonshotai/kimi-k2.5, backend: opencode, timeout_minutes: 120}
  - {role: critic, model: claude-haiku-4-5-20251001, backend: claude, timeout_minutes: 30}
  - {role: finalize, model: nvidia/moonshotai/kimi-k2.5, backend: opencode, timeout_minutes: 30}
  - {role: review, model: claude-opus-4-6, backend: claude, timeout_minutes: 45}
EOF
    ok "Router config at .langywrap/router.yaml"
}

couple_compound() {
    $C_COMPOUND || return 0
    step "Setting up compound engineering..."
    $DRY_RUN && { info "[dry-run] docs/solutions/"; return; }
    mkdir -p "$PROJECT_DIR/docs/solutions" "$PROJECT_DIR/docs/agent-guides" "$PROJECT_DIR/notes"
    [[ -f "$PROJECT_DIR/docs/solutions/_template.md" ]] || \
        cp "$LANGYWRAP_DIR/docs/solutions/_template.md" "$PROJECT_DIR/docs/solutions/"
    ok "Compound engineering ready"
}

couple_wrappers() {
    $C_WRAPPERS || return 0
    step "Installing wrappers..."
    $DRY_RUN && { info "[dry-run] ./just ./uv"; return; }
    for w in just uv; do
        local src="$LANGYWRAP_DIR/lib/langywrap/helpers/bash/${w}-wrapper"
        [[ -f "$PROJECT_DIR/$w" ]] && { ok "$w wrapper exists"; continue; }
        [[ -f "$src" ]] && { cp "$src" "$PROJECT_DIR/$w"; chmod +x "$PROJECT_DIR/$w"; ok "$w wrapper"; }
    done
}

couple_dev_dep() {
    $C_DEV_DEP || return 0
    step "Adding langywrap dev dependency..."
    $DRY_RUN && { info "[dry-run] uv add --dev langywrap"; return; }
    if [[ -f "$PROJECT_DIR/pyproject.toml" ]] && command -v uv &>/dev/null; then
        (cd "$PROJECT_DIR" && uv add --dev "langywrap @ file://$LANGYWRAP_DIR" 2>&1 | tail -3) || \
            warn "Manual: uv add --dev 'langywrap @ file://$LANGYWRAP_DIR'"
    else
        info "Manual: uv add --dev 'langywrap @ file://$LANGYWRAP_DIR'"
    fi
}

show_post_couple() {
    header "Coupling Complete!"
    echo -e "${BOLD}$PROJECT_NAME${NC} is coupled to langywrap.\n"

    echo -e "${BOLD}Run AI tools with security:${NC}"
    $C_EXECWRAP && {
        echo -e "  ${CYAN}$PROJECT_DIR/.exec/execwrap.bash claude${NC}"
        echo -e "  ${CYAN}$PROJECT_DIR/.exec/execwrap.bash opencode${NC}"
        echo -e "  ${DIM}Tip: alias cw='$PROJECT_DIR/.exec/execwrap.bash claude'${NC}"
        echo -e "  ${DIM}     alias ow='$PROJECT_DIR/.exec/execwrap.bash opencode'${NC}"
    }
    echo ""

    $C_RALPH && {
        echo -e "${BOLD}Ralph loop:${NC}"
        echo -e "  ${CYAN}cd $PROJECT_DIR && langywrap ralph run --budget 10${NC}"
        echo ""
    }

    $C_HYPERAGENTS && {
        echo -e "${BOLD}Router:${NC} ${CYAN}.langywrap/router.yaml${NC} (HyperAgents evolve this)"
        echo ""
    }

    $C_COMPOUND && {
        echo -e "${BOLD}Compound:${NC} ${CYAN}langywrap compound push docs/solutions/lesson.md${NC}"
        echo ""
    }

    echo -e "${BOLD}Rerun:${NC} ${CYAN}$LANGYWRAP_DIR/scripts/couple.sh $PROJECT_DIR${NC}"
    echo ""
}

# --- Main ---
main() {
    echo -e "\n${BOLD}${CYAN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║   langywrap — Project Coupling Wizard      ║${NC}"
    echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════╝${NC}\n"
    info "Project:   $PROJECT_DIR"
    info "langywrap: $LANGYWRAP_DIR"
    $DRY_RUN && warn "DRY RUN mode"
    echo ""

    # Detect existing coupling
    if [[ -d "$PROJECT_DIR/.langywrap" ]] && ! $NON_INTERACTIVE; then
        warn "Project already coupled (found .langywrap/)"
        echo ""
        if ask_yn "  Update existing coupling?" "y"; then
            info "Updating — existing config will be overwritten"
        else
            info "Cancelled."
            exit 0
        fi
        echo ""
    fi

    [[ -z "$PRESET" ]] && ! $NON_INTERACTIVE && coupling_wizard

    header "Summary for $PROJECT_NAME"
    $C_SECURITY && ok "Security" || echo -e "  ${DIM}Skip: Security${NC}"
    $C_EXECWRAP && ok "ExecWrap" || echo -e "  ${DIM}Skip: ExecWrap${NC}"
    $C_GIT_HOOKS && ok "Git hooks" || echo -e "  ${DIM}Skip: Git hooks${NC}"
    $C_RTK && ok "RTK" || echo -e "  ${DIM}Skip: RTK${NC}"
    $C_RALPH && ok "Ralph" || echo -e "  ${DIM}Skip: Ralph${NC}"
    $C_HYPERAGENTS && ok "HyperAgents" || echo -e "  ${DIM}Skip: HyperAgents${NC}"
    $C_COMPOUND && ok "Compound" || echo -e "  ${DIM}Skip: Compound${NC}"
    $C_QUALITY && ok "Quality" || echo -e "  ${DIM}Skip: Quality${NC}"
    $C_WRAPPERS && ok "Wrappers" || echo -e "  ${DIM}Skip: Wrappers${NC}"
    $C_DEV_DEP && ok "Dev dep" || echo -e "  ${DIM}Skip: Dev dep${NC}"
    echo ""

    ! $NON_INTERACTIVE && ! $DRY_RUN && { ask_yn "Proceed?" "y" || { info "Cancelled."; exit 0; }; }

    couple_config
    couple_security
    couple_execwrap
    couple_git_hooks
    couple_ralph
    couple_hyperagents
    couple_compound
    couple_wrappers
    couple_dev_dep

    show_post_couple
}

main "$@"
