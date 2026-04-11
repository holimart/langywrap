#!/usr/bin/env bash
# =============================================================================
# langywrap — Interactive Installation Wizard
# =============================================================================
# Installs langywrap system-wide with an interactive feature selection.
# Idempotent — safe to rerun. Reruns let you change your setup.
#
# Usage:
#   ./install.sh              Interactive wizard (recommended)
#   ./install.sh --defaults   Accept all defaults non-interactively
#   ./install.sh --dry-run    Show what would happen
#   ./install.sh --help       Show help
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors and formatting
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

LANGYWRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANGYWRAP_CONFIG_DIR="$HOME/.langywrap"

# ---------------------------------------------------------------------------
# State file — remembers previous choices for rerun
# ---------------------------------------------------------------------------
STATE_FILE="$LANGYWRAP_CONFIG_DIR/install_state.env"

# Defaults (overridden by state file or user choices)
OPT_PYTHON_PACKAGE=true
OPT_RTK=true
OPT_OPENWOLF=true
OPT_GLOBAL_CONFIG=true
OPT_GLOBAL_MODE="symlinks"   # symlinks | copy
OPT_EXECWRAP=true
OPT_SECURITY_HOOKS=true
OPT_GIT_HOOKS=true
OPT_SKILLS=true
OPT_HYPERAGENTS=true
OPT_COMPOUND=true
DRY_RUN=false
NON_INTERACTIVE=false

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
ok()      { echo -e "${GREEN}✓${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
err()     { echo -e "${RED}✗${NC}  $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}\n"; }
step()    { echo -e "${MAGENTA}→${NC} $*"; }
dry()     { if $DRY_RUN; then echo -e "${DIM}[dry-run]${NC} $*"; return 0; fi; return 1; }

ask_yn() {
    local prompt="$1" default="${2:-y}"
    if $NON_INTERACTIVE; then
        [[ "$default" == "y" ]] && return 0 || return 1
    fi
    local yn
    if [[ "$default" == "y" ]]; then
        read -rp "$(echo -e "${BOLD}$prompt${NC} [Y/n] ")" yn
        [[ -z "$yn" || "$yn" =~ ^[Yy] ]]
    else
        read -rp "$(echo -e "${BOLD}$prompt${NC} [y/N] ")" yn
        [[ "$yn" =~ ^[Yy] ]]
    fi
}

ask_choice() {
    local prompt="$1" default="$2"
    shift 2
    local options=("$@")
    if $NON_INTERACTIVE; then echo "$default"; return; fi

    echo -e "${BOLD}$prompt${NC} (default: $default)"
    for i in "${!options[@]}"; do
        echo -e "  ${CYAN}$((i+1)))${NC} ${options[$i]}"
    done
    local choice
    read -rp "Choice [1-${#options[@]}]: " choice
    if [[ -z "$choice" ]]; then
        echo "$default"
    elif [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
        echo "${options[$((choice-1))]}"
    else
        echo "$default"
    fi
}

# ---------------------------------------------------------------------------
# Parse CLI arguments
# ---------------------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --dry-run)        DRY_RUN=true ;;
        --defaults)       NON_INTERACTIVE=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--defaults] [--dry-run] [--help]"
            echo ""
            echo "  --defaults   Accept all defaults non-interactively"
            echo "  --dry-run    Show what would happen without doing it"
            echo "  --help       Show this help"
            exit 0 ;;
        *) err "Unknown option: $arg"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Load previous state if rerunning
# ---------------------------------------------------------------------------
load_previous_state() {
    if [[ -f "$STATE_FILE" ]]; then
        warn "Previous installation detected. Your previous choices will be shown as defaults."
        # shellcheck source=/dev/null
        source "$STATE_FILE" 2>/dev/null || true
    fi
}

save_state() {
    mkdir -p "$LANGYWRAP_CONFIG_DIR"
    cat > "$STATE_FILE" << EOF
# langywrap install state — generated $(date -Iseconds)
OPT_PYTHON_PACKAGE=$OPT_PYTHON_PACKAGE
OPT_RTK=$OPT_RTK
OPT_OPENWOLF=$OPT_OPENWOLF
OPT_GLOBAL_CONFIG=$OPT_GLOBAL_CONFIG
OPT_GLOBAL_MODE=$OPT_GLOBAL_MODE
OPT_EXECWRAP=$OPT_EXECWRAP
OPT_SECURITY_HOOKS=$OPT_SECURITY_HOOKS
OPT_GIT_HOOKS=$OPT_GIT_HOOKS
OPT_SKILLS=$OPT_SKILLS
OPT_HYPERAGENTS=$OPT_HYPERAGENTS
OPT_COMPOUND=$OPT_COMPOUND
EOF
}

# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------
check_prerequisites() {
    header "Checking prerequisites"
    local missing=()

    if command -v python3 &>/dev/null; then
        local pyver
        pyver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        ok "Python $pyver"
        if python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            :
        elif command -v uv &>/dev/null && uv python find ">=3.10" &>/dev/null; then
            local uv_py
            uv_py=$(uv python find ">=3.10" 2>/dev/null | head -1)
            ok "Python via uv: $uv_py (system $pyver is old but uv provides 3.10+)"
        else
            err "Python >= 3.10 required (found $pyver). uv can install it: uv python install 3.11"
            missing+=(python3.10+)
        fi
    elif command -v uv &>/dev/null && uv python find ">=3.10" &>/dev/null; then
        local uv_py
        uv_py=$(uv python find ">=3.10" 2>/dev/null | head -1)
        ok "Python via uv: $uv_py"
    else
        err "python3 not found. Install Python 3.10+ or run: uv python install 3.11"
        missing+=(python3)
    fi

    if command -v git &>/dev/null; then
        ok "git $(git --version | cut -d' ' -f3)"
    else
        err "git not found"; missing+=(git)
    fi

    if command -v uv &>/dev/null; then
        ok "uv $(uv --version 2>/dev/null | head -1)"
    else
        warn "uv not found — will use pip as fallback"
    fi

    if command -v cargo &>/dev/null; then
        ok "cargo $(cargo --version | cut -d' ' -f2) (for RTK build)"
    else
        warn "cargo not found — RTK build will be skipped"
        OPT_RTK=false
    fi

    if command -v node &>/dev/null; then
        local node_ver
        node_ver=$(node -v)
        ok "node $node_ver (for OpenWolf build)"
        local node_major
        node_major=$(echo "$node_ver" | sed 's/v//' | cut -d. -f1)
        if (( node_major < 20 )); then
            warn "Node.js >= 20 required for OpenWolf (found $node_ver) — OpenWolf build will be skipped"
            OPT_OPENWOLF=false
        fi
    else
        warn "node not found — OpenWolf build will be skipped"
        OPT_OPENWOLF=false
    fi

    if command -v pnpm &>/dev/null; then
        ok "pnpm $(pnpm --version 2>/dev/null | head -1) (for OpenWolf build)"
    else
        if $OPT_OPENWOLF; then
            warn "pnpm not found — OpenWolf build will be skipped. Install with: npm install -g pnpm"
            OPT_OPENWOLF=false
        fi
    fi

    if command -v just &>/dev/null; then
        ok "just $(just --version 2>/dev/null | head -1)"
    else
        warn "just not found — install with: cargo install just"
    fi

    if (( ${#missing[@]} > 0 )); then
        err "Missing required tools: ${missing[*]}"
        err "Install them and rerun this script."
        exit 1
    fi
    echo ""
}

# ---------------------------------------------------------------------------
# Feature selection wizard
# ---------------------------------------------------------------------------
feature_wizard() {
    header "Feature Selection"
    echo -e "langywrap provides these features. Select what you'd like to install.\n"

    echo -e "${BOLD}Core (recommended):${NC}"
    echo -e "  ${GREEN} 1)${NC} Python package    — lib/langywrap/ installed via uv/pip (editable mode)"
    echo -e "  ${GREEN} 2)${NC} RTK compression   — Build token-saving output compressor from source"
    echo -e "  ${GREEN} 3)${NC} OpenWolf          — Token-conscious AI brain for Claude Code (~80% savings)"
    echo -e "  ${GREEN} 4)${NC} Global config     — Manage ~/.claude/ hooks, settings, CLAUDE.md"
    echo -e ""
    echo -e "${BOLD}Security:${NC}"
    echo -e "  ${GREEN} 5)${NC} ExecWrap          — 5-layer execution wrapper for AI tools"
    echo -e "  ${GREEN} 6)${NC} Security hooks    — Per-tool hooks (Claude, OpenCode, Cursor, Cline)"
    echo -e "  ${GREEN} 7)${NC} Git hooks         — Pre-commit (Python scan) + pre-push (force-push block)"
    echo -e ""
    echo -e "${BOLD}AI Agent Infrastructure:${NC}"
    echo -e "  ${GREEN} 8)${NC} Skills            — Claude Code slash commands (symlinked globally)"
    echo -e "  ${GREEN} 9)${NC} HyperAgents       — Agent evolution framework + experiment archive"
    echo -e "  ${GREEN}10)${NC} Compound eng.     — Cross-project lessons learned hub"
    echo ""

    if ! $NON_INTERACTIVE; then
        echo -e "${DIM}Press Enter to accept defaults, or type y/n for each:${NC}\n"
    fi

    local default_yn
    default_yn() { $1 && echo "y" || echo "n"; }

    ask_yn "  1) Install Python package?" "$(default_yn $OPT_PYTHON_PACKAGE)" && OPT_PYTHON_PACKAGE=true || OPT_PYTHON_PACKAGE=false
    ask_yn "  2) Build RTK from source?" "$(default_yn $OPT_RTK)" && OPT_RTK=true || OPT_RTK=false
    ask_yn "  3) Build OpenWolf from source?" "$(default_yn $OPT_OPENWOLF)" && OPT_OPENWOLF=true || OPT_OPENWOLF=false
    ask_yn "  4) Set up global Claude config?" "$(default_yn $OPT_GLOBAL_CONFIG)" && OPT_GLOBAL_CONFIG=true || OPT_GLOBAL_CONFIG=false

    if $OPT_GLOBAL_CONFIG; then
        local mode
        mode=$(ask_choice "     Config mode?" "$OPT_GLOBAL_MODE" "symlinks" "copy")
        OPT_GLOBAL_MODE="$mode"
    fi

    ask_yn "  5) Install ExecWrap wrapper?" "$(default_yn $OPT_EXECWRAP)" && OPT_EXECWRAP=true || OPT_EXECWRAP=false
    ask_yn "  6) Install security hooks?" "$(default_yn $OPT_SECURITY_HOOKS)" && OPT_SECURITY_HOOKS=true || OPT_SECURITY_HOOKS=false
    ask_yn "  7) Install git hooks?" "$(default_yn $OPT_GIT_HOOKS)" && OPT_GIT_HOOKS=true || OPT_GIT_HOOKS=false
    ask_yn "  8) Install Claude skills globally?" "$(default_yn $OPT_SKILLS)" && OPT_SKILLS=true || OPT_SKILLS=false
    ask_yn "  9) Set up HyperAgents framework?" "$(default_yn $OPT_HYPERAGENTS)" && OPT_HYPERAGENTS=true || OPT_HYPERAGENTS=false
    ask_yn " 10) Set up compound engineering hub?" "$(default_yn $OPT_COMPOUND)" && OPT_COMPOUND=true || OPT_COMPOUND=false

    echo ""
    save_state
}

# ---------------------------------------------------------------------------
# Installation steps
# ---------------------------------------------------------------------------

install_python_package() {
    if ! $OPT_PYTHON_PACKAGE; then return; fi
    header "Installing Python package"

    if dry "uv pip install -e $LANGYWRAP_DIR"; then return; fi

    if command -v uv &>/dev/null; then
        step "Installing via uv (editable mode)..."
        (cd "$LANGYWRAP_DIR" && uv sync 2>&1 | tail -3)
        ok "Python package installed (editable: $LANGYWRAP_DIR)"
    else
        step "Installing via pip (editable mode)..."
        python3 -m pip install -e "$LANGYWRAP_DIR" 2>&1 | tail -3
        ok "Python package installed via pip"
    fi
}

install_rtk() {
    if ! $OPT_RTK; then return; fi
    header "Building RTK from source"

    if ! command -v cargo &>/dev/null; then
        warn "cargo not found — skipping RTK. Install Rust: https://rustup.rs"
        return
    fi

    if dry "cd rtk && cargo build --release && cp target/release/rtk ~/.local/bin/"; then return; fi

    step "Building RTK (this may take a few minutes on first run)..."
    (cd "$LANGYWRAP_DIR/rtk" && cargo build --release 2>&1 | tail -5)

    mkdir -p "$HOME/.local/bin"
    cp "$LANGYWRAP_DIR/rtk/target/release/rtk" "$HOME/.local/bin/rtk"
    chmod +x "$HOME/.local/bin/rtk"

    if "$HOME/.local/bin/rtk" --version &>/dev/null; then
        ok "RTK installed: $("$HOME/.local/bin/rtk" --version 2>&1 | head -1)"
    else
        warn "RTK binary built but --version check failed"
    fi

    # Also put in langywrap's own execwrap dir
    cp "$HOME/.local/bin/rtk" "$LANGYWRAP_DIR/execwrap/rtk" 2>/dev/null || true
}

install_openwolf() {
    if ! $OPT_OPENWOLF; then return; fi
    header "Building OpenWolf from source"

    if ! command -v node &>/dev/null; then
        warn "node not found — skipping OpenWolf. Install Node.js >= 20"
        return
    fi
    if ! command -v pnpm &>/dev/null; then
        warn "pnpm not found — skipping OpenWolf. Install with: npm install -g pnpm"
        return
    fi

    if dry "cd openwolf && pnpm install && pnpm build && link to ~/.local/bin/"; then return; fi

    step "Building OpenWolf (this may take a minute on first run)..."
    (cd "$LANGYWRAP_DIR/openwolf" && pnpm install 2>&1 | tail -3)
    (cd "$LANGYWRAP_DIR/openwolf" && pnpm build 2>&1 | tail -5)

    mkdir -p "$HOME/.local/bin"
    cat > "$HOME/.local/bin/openwolf" << WRAPPER
#!/usr/bin/env bash
exec node "$LANGYWRAP_DIR/openwolf/dist/bin/openwolf.js" "\$@"
WRAPPER
    chmod +x "$HOME/.local/bin/openwolf"

    if "$HOME/.local/bin/openwolf" --version &>/dev/null; then
        ok "OpenWolf installed: $("$HOME/.local/bin/openwolf" --version 2>&1 | head -1)"
    else
        warn "OpenWolf built but --version check failed"
    fi
}

install_global_config() {
    if ! $OPT_GLOBAL_CONFIG; then return; fi
    header "Setting up global Claude config"

    local claude_dir="$HOME/.claude"
    mkdir -p "$claude_dir"

    local do_link=$( [[ "$OPT_GLOBAL_MODE" == "symlinks" ]] && echo true || echo false )

    # --- Hooks ---
    if $OPT_SECURITY_HOOKS; then
        step "Installing global hooks..."
        if dry "link/copy $LANGYWRAP_DIR/hooks/claude/ -> $claude_dir/hooks/"; then :
        elif $do_link; then
            # Backup existing hooks
            if [[ -d "$claude_dir/hooks" && ! -L "$claude_dir/hooks" ]]; then
                mv "$claude_dir/hooks" "$claude_dir/hooks.bak.$(date +%s)"
                warn "Existing hooks backed up to hooks.bak.*"
            fi
            ln -sfn "$LANGYWRAP_DIR/hooks/claude" "$claude_dir/hooks"
            ok "Hooks symlinked: $claude_dir/hooks -> langywrap/hooks/claude/"
        else
            mkdir -p "$claude_dir/hooks"
            cp "$LANGYWRAP_DIR/hooks/claude/"* "$claude_dir/hooks/"
            ok "Hooks copied to $claude_dir/hooks/"
        fi
    fi

    # --- Skills ---
    if $OPT_SKILLS; then
        step "Installing global skills..."
        if dry "link/copy $LANGYWRAP_DIR/skills/ -> $claude_dir/commands/"; then :
        elif $do_link; then
            if [[ -d "$claude_dir/commands" && ! -L "$claude_dir/commands" ]]; then
                mv "$claude_dir/commands" "$claude_dir/commands.bak.$(date +%s)"
                warn "Existing commands backed up to commands.bak.*"
            fi
            ln -sfn "$LANGYWRAP_DIR/skills" "$claude_dir/commands"
            ok "Skills symlinked: $claude_dir/commands -> langywrap/skills/"
        else
            mkdir -p "$claude_dir/commands"
            cp "$LANGYWRAP_DIR/skills/"*.md "$claude_dir/commands/"
            ok "Skills copied to $claude_dir/commands/"
        fi
    fi

    # --- Settings.json merge (additive) ---
    step "Merging security rules into settings.json..."
    if dry "merge $LANGYWRAP_DIR/configs/claude-settings.json -> $claude_dir/settings.json"; then :
    elif command -v jq &>/dev/null; then
        if [[ -f "$claude_dir/settings.json" ]]; then
            # Additive merge — never remove user entries
            jq -s '.[0] * .[1]' "$claude_dir/settings.json" "$LANGYWRAP_DIR/configs/claude-settings.json" > "$claude_dir/settings.json.tmp"
            mv "$claude_dir/settings.json.tmp" "$claude_dir/settings.json"
            ok "Settings merged (additive)"
        else
            cp "$LANGYWRAP_DIR/configs/claude-settings.json" "$claude_dir/settings.json"
            ok "Settings installed"
        fi
    else
        warn "jq not found — skipping settings.json merge. Install jq for full setup."
    fi

    # --- Store hub path ---
    echo "$LANGYWRAP_DIR" > "$LANGYWRAP_CONFIG_DIR/hub_path"
    ok "Hub path stored: $LANGYWRAP_CONFIG_DIR/hub_path"
}

install_system_permissions() {
    header "Setting up system-wide security"

    mkdir -p "$LANGYWRAP_CONFIG_DIR/defaults" "$LANGYWRAP_CONFIG_DIR/logs"

    if dry "cp permissions.yaml -> $LANGYWRAP_CONFIG_DIR/defaults/"; then return; fi

    cp "$LANGYWRAP_DIR/lib/langywrap/security/defaults/permissions.yaml" \
       "$LANGYWRAP_CONFIG_DIR/defaults/permissions.yaml"
    cp "$LANGYWRAP_DIR/lib/langywrap/security/defaults/resources.yaml" \
       "$LANGYWRAP_CONFIG_DIR/defaults/resources.yaml"
    ok "System-wide permissions installed at $LANGYWRAP_CONFIG_DIR/defaults/"
    info "These denials can NEVER be overridden by per-project config."
}

install_hyperagents() {
    if ! $OPT_HYPERAGENTS; then return; fi
    header "Setting up HyperAgents framework"

    if dry "mkdir experiments/archive, configs"; then return; fi

    mkdir -p "$LANGYWRAP_DIR/experiments/archive"
    mkdir -p "$LANGYWRAP_DIR/experiments/results"
    ok "HyperAgent archive ready at experiments/archive/"
    info "Every coupled repo will contribute to agent evolution via ralph loops."
}

install_compound() {
    if ! $OPT_COMPOUND; then return; fi
    header "Setting up compound engineering hub"

    if dry "mkdir docs/solutions"; then return; fi

    mkdir -p "$LANGYWRAP_DIR/docs/solutions"
    mkdir -p "$LANGYWRAP_DIR/docs/agent-guides"
    mkdir -p "$LANGYWRAP_DIR/docs/processes"
    ok "Compound engineering hub ready at docs/solutions/"
    info "Downstream repos push lessons here via: langywrap compound push"
}

# ---------------------------------------------------------------------------
# Post-install guidance
# ---------------------------------------------------------------------------
show_post_install() {
    header "Installation Complete!"

    echo -e "${BOLD}How to run AI tools through langywrap:${NC}\n"

    if $OPT_EXECWRAP; then
        echo -e "  ${CYAN}Claude Code (with execwrap security):${NC}"
        echo -e "    ${BOLD}$LANGYWRAP_DIR/execwrap/execwrap.bash claude${NC}"
        echo -e ""
        echo -e "  ${CYAN}OpenCode (with execwrap security):${NC}"
        echo -e "    ${BOLD}$LANGYWRAP_DIR/execwrap/execwrap.bash opencode${NC}"
        echo -e ""
        echo -e "  ${DIM}Tip: Create aliases in your shell rc file:${NC}"
        echo -e "    ${DIM}alias cw='$LANGYWRAP_DIR/execwrap/execwrap.bash claude'${NC}"
        echo -e "    ${DIM}alias ow='$LANGYWRAP_DIR/execwrap/execwrap.bash opencode'${NC}"
        echo -e ""
    else
        echo -e "  Run ${BOLD}claude${NC} or ${BOLD}opencode${NC} normally — global hooks provide security."
        echo -e ""
    fi

    echo -e "${BOLD}Useful commands:${NC}\n"
    echo -e "  ${CYAN}./just check${NC}         — Run lint + typecheck + tests"
    echo -e "  ${CYAN}./just couple PATH${NC}   — Couple a downstream repo"
    echo -e "  ${CYAN}langywrap --help${NC}     — CLI help"
    echo -e ""

    if $OPT_SKILLS; then
        echo -e "${BOLD}Available Claude Code skills:${NC}\n"
        for f in "$LANGYWRAP_DIR/skills/"*.md; do
            local name
            name=$(basename "$f" .md)
            echo -e "  ${CYAN}/$name${NC}"
        done
        echo ""
    fi

    echo -e "${BOLD}Next steps:${NC}\n"
    echo -e "  1. Couple your first project:  ${CYAN}./just couple /path/to/project${NC}"
    echo -e "  2. Run a ralph loop:           ${CYAN}cd /path/to/project && langywrap ralph run${NC}"
    echo -e "  3. Rerun this installer:       ${CYAN}./install.sh${NC} (change any choices)"
    echo ""

    if $DRY_RUN; then
        echo -e "${YELLOW}This was a dry run — no changes were made.${NC}"
        echo -e "Run without ${BOLD}--dry-run${NC} to apply.\n"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo -e "\n${BOLD}${CYAN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║   langywrap — Installation Wizard          ║${NC}"
    echo -e "${BOLD}${CYAN}║   Universal AI Agent Orchestration Toolkit  ║${NC}"
    echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════╝${NC}\n"

    info "langywrap directory: $LANGYWRAP_DIR"
    $DRY_RUN && warn "DRY RUN mode — no changes will be made"
    echo ""

    load_previous_state
    check_prerequisites
    feature_wizard

    # Show summary before proceeding
    header "Installation Summary"
    $OPT_PYTHON_PACKAGE && ok "Python package (editable)" || echo -e "  ${DIM}Skip: Python package${NC}"
    $OPT_RTK && ok "RTK (build from source)" || echo -e "  ${DIM}Skip: RTK${NC}"
    $OPT_OPENWOLF && ok "OpenWolf (build from source)" || echo -e "  ${DIM}Skip: OpenWolf${NC}"
    $OPT_GLOBAL_CONFIG && ok "Global config ($OPT_GLOBAL_MODE)" || echo -e "  ${DIM}Skip: Global config${NC}"
    $OPT_EXECWRAP && ok "ExecWrap wrapper" || echo -e "  ${DIM}Skip: ExecWrap${NC}"
    $OPT_SECURITY_HOOKS && ok "Security hooks" || echo -e "  ${DIM}Skip: Security hooks${NC}"
    $OPT_GIT_HOOKS && ok "Git hooks" || echo -e "  ${DIM}Skip: Git hooks${NC}"
    $OPT_SKILLS && ok "Skills (global)" || echo -e "  ${DIM}Skip: Skills${NC}"
    $OPT_HYPERAGENTS && ok "HyperAgents" || echo -e "  ${DIM}Skip: HyperAgents${NC}"
    $OPT_COMPOUND && ok "Compound engineering" || echo -e "  ${DIM}Skip: Compound eng.${NC}"
    echo ""

    if ! $NON_INTERACTIVE && ! $DRY_RUN; then
        ask_yn "Proceed with installation?" "y" || { info "Cancelled."; exit 0; }
    fi

    # Execute
    install_python_package
    install_rtk
    install_openwolf
    install_system_permissions
    install_global_config
    install_hyperagents
    install_compound

    show_post_install
}

main "$@"
