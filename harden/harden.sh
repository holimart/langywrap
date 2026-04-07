#!/usr/bin/env bash
# ============================================================================
# LLM Security Toolkit - Repository Hardening Tool
# ============================================================================
#
# Hardens a repository with security hooks for AI coding tools.
# Supports: Claude Code, OpenCode, Cursor, Cline, Windsurf
# Universal: Git hooks (pre-commit, pre-push) work with ALL tools
#
# Usage: harden.sh [TARGET_DIR] [OPTIONS]
#   TARGET_DIR         Directory to harden (default: current directory)
#   --tool TOOL        Target tool: claude-code, opencode, cursor, cline, windsurf, all
#                      (default: auto-detect)
#   --project NAME     Project name for audit logs (default: directory basename)
#   --no-hooks         Skip tool-specific hooks setup
#   --no-git-hooks     Skip git pre-commit/pre-push hook setup
#   --no-settings      Skip settings/config modifications
#   --with-wrapper     Also install shell wrapper (for tools without native hooks)
#   --dry-run          Show what would be done without doing it
#   --help             Show this help message
# ============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# Find llmsec project root (where templates live)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLMSEC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEMPLATES_DIR="$LLMSEC_ROOT/templates"

# Defaults
TARGET_DIR=""
TOOL=""
PROJECT_NAME=""
SKIP_HOOKS=false
SKIP_GIT_HOOKS=false
SKIP_SETTINGS=false
WITH_WRAPPER=false
DRY_RUN=false

# Counters
FILES_CREATED=0
FILES_MODIFIED=0

# ============================================================================
# Utility functions
# ============================================================================

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERR]${NC}  $1"; }
log_dry()  { echo -e "${YELLOW}[DRY]${NC}  Would: $1"; }

do_action() {
    # $1 = description, rest = command
    local desc="$1"
    shift
    if $DRY_RUN; then
        log_dry "$desc"
    else
        "$@"
    fi
}

copy_template() {
    local src="$1"
    local dest="$2"
    local desc="${3:-$dest}"

    if $DRY_RUN; then
        log_dry "Create $desc"
        return
    fi

    mkdir -p "$(dirname "$dest")"
    # Replace template variables
    sed -e "s/__PROJECT_NAME__/$PROJECT_NAME/g" \
        -e "s|__REAL_SHELL__|$(command -v bash)|g" \
        "$src" > "$dest"

    FILES_CREATED=$((FILES_CREATED + 1))
    log_ok "Created $desc"
}

make_executable() {
    local file="$1"
    if $DRY_RUN; then
        log_dry "chmod +x $file"
    else
        chmod +x "$file"
    fi
}

merge_json() {
    local fragment="$1"
    local target="$2"
    local desc="${3:-$target}"

    if ! command -v jq &>/dev/null; then
        log_err "jq is required for merging JSON configs. Install with: apt install jq"
        return 1
    fi

    if $DRY_RUN; then
        log_dry "Merge settings into $desc"
        return
    fi

    if [[ -f "$target" ]]; then
        # Deep merge: fragment into existing
        local merged
        merged=$(jq -s '.[0] * .[1]' "$target" "$fragment")
        echo "$merged" > "$target"
        FILES_MODIFIED=$((FILES_MODIFIED + 1))
        log_ok "Merged settings into $desc"
    else
        mkdir -p "$(dirname "$target")"
        cp "$fragment" "$target"
        FILES_CREATED=$((FILES_CREATED + 1))
        log_ok "Created $desc"
    fi
}

# ============================================================================
# Auto-detection
# ============================================================================

detect_tool() {
    local dir="$1"
    local detected=""

    if [[ -d "$dir/.claude" ]]; then
        detected="claude-code"
    elif [[ -f "$dir/opencode.json" ]] || [[ -d "$dir/.opencode" ]]; then
        detected="opencode"
    elif [[ -d "$dir/.cursor" ]]; then
        detected="cursor"
    elif [[ -d "$dir/.clinerules" ]] || [[ -f "$dir/.clinerules" ]]; then
        detected="cline"
    elif [[ -f "$dir/.windsurfrules" ]]; then
        detected="windsurf"
    fi

    echo "$detected"
}

# ============================================================================
# Tool-specific installation
# ============================================================================

install_claude_code() {
    local dir="$1"
    log_info "Setting up Claude Code security..."

    if ! $SKIP_HOOKS; then
        copy_template "$TEMPLATES_DIR/claude-code/hooks/security_hook.sh" \
                      "$dir/.claude/hooks/security_hook.sh" \
                      ".claude/hooks/security_hook.sh"
        make_executable "$dir/.claude/hooks/security_hook.sh"
    fi

    if ! $SKIP_SETTINGS; then
        # Create temp fragment with project-specific replacements
        local tmp_fragment="/tmp/llmsec_claude_fragment_$$.json"
        sed "s/__PROJECT_NAME__/$PROJECT_NAME/g" \
            "$TEMPLATES_DIR/claude-code/settings-fragment.json" > "$tmp_fragment"
        merge_json "$tmp_fragment" "$dir/.claude/settings.json" ".claude/settings.json"
        rm -f "$tmp_fragment"
    fi
}

install_opencode() {
    local dir="$1"
    log_info "Setting up OpenCode security..."

    if ! $SKIP_HOOKS; then
        copy_template "$TEMPLATES_DIR/opencode/plugins/security-guard.ts" \
                      "$dir/.opencode/plugins/security-guard.ts" \
                      ".opencode/plugins/security-guard.ts"
    fi

    if ! $SKIP_SETTINGS; then
        local tmp_fragment="/tmp/llmsec_opencode_fragment_$$.json"
        sed "s/__PROJECT_NAME__/$PROJECT_NAME/g" \
            "$TEMPLATES_DIR/opencode/permissions-fragment.json" > "$tmp_fragment"
        local target="$dir/opencode.json"
        [[ -d "$dir/.opencode" ]] && target="$dir/.opencode/config.json"
        merge_json "$tmp_fragment" "$target" "$(basename "$target")"
        rm -f "$tmp_fragment"
    fi
}

install_cursor() {
    local dir="$1"
    log_info "Setting up Cursor security..."

    if ! $SKIP_HOOKS; then
        copy_template "$TEMPLATES_DIR/cursor/hooks/guard.sh" \
                      "$dir/.cursor/hooks/guard.sh" \
                      ".cursor/hooks/guard.sh"
        make_executable "$dir/.cursor/hooks/guard.sh"
    fi

    if ! $SKIP_SETTINGS; then
        local tmp_fragment="/tmp/llmsec_cursor_fragment_$$.json"
        sed "s/__PROJECT_NAME__/$PROJECT_NAME/g" \
            "$TEMPLATES_DIR/cursor/hooks.json" > "$tmp_fragment"
        merge_json "$tmp_fragment" "$dir/.cursor/hooks.json" ".cursor/hooks.json"
        rm -f "$tmp_fragment"
    fi
}

install_cline() {
    local dir="$1"
    log_info "Setting up Cline security..."

    if ! $SKIP_HOOKS; then
        local hooks_dir="$dir/.clinerules/hooks"
        [[ -f "$dir/.clinerules" ]] && hooks_dir="$dir/.cline/hooks"
        copy_template "$TEMPLATES_DIR/cline/hooks/PreToolUse" \
                      "$hooks_dir/PreToolUse" \
                      "cline hooks/PreToolUse"
        make_executable "$hooks_dir/PreToolUse"
    fi
}

install_windsurf() {
    local dir="$1"
    log_info "Setting up Windsurf security..."

    echo ""
    log_warn "Windsurf uses VS Code settings.json for deny lists."
    log_warn "Add these entries to your VS Code settings.json manually:"
    echo ""
    echo -e "${BOLD}Settings > cascade.commandsDenyList:${NC}"
    jq -r '.["cascade.commandsDenyList"][]' "$TEMPLATES_DIR/windsurf/settings-fragment.json" 2>/dev/null | \
        while read -r entry; do echo "  - $entry"; done
    echo ""
    log_info "Or copy from: $TEMPLATES_DIR/windsurf/settings-fragment.json"
}

install_git_hooks() {
    local dir="$1"
    log_info "Setting up git hooks..."

    if ! git -C "$dir" rev-parse --is-inside-work-tree &>/dev/null; then
        log_warn "Not a git repository: $dir (skipping git hooks)"
        return
    fi

    copy_template "$TEMPLATES_DIR/githooks/pre-commit" \
                  "$dir/.githooks/pre-commit" \
                  ".githooks/pre-commit"
    make_executable "$dir/.githooks/pre-commit"

    copy_template "$TEMPLATES_DIR/githooks/pre-push" \
                  "$dir/.githooks/pre-push" \
                  ".githooks/pre-push"
    make_executable "$dir/.githooks/pre-push"

    if ! $DRY_RUN; then
        git -C "$dir" config core.hooksPath .githooks
        log_ok "Set git core.hooksPath = .githooks"
    else
        log_dry "Set git core.hooksPath = .githooks"
    fi
}

install_shell_wrapper() {
    local dir="$1"
    log_info "Setting up shell wrapper..."

    # guard.sh = check-only validator (default, used by execwrap as pre-check)
    copy_template "$TEMPLATES_DIR/shell-wrapper/guard.sh" \
                  "$dir/.llmsec/guard.sh" \
                  ".llmsec/guard.sh"
    make_executable "$dir/.llmsec/guard.sh"

    # guard-exec.sh = shell replacement that checks AND executes (use as $SHELL for AI tools)
    if $DRY_RUN; then
        log_dry "Create .llmsec/guard-exec.sh"
    else
        cat > "$dir/.llmsec/guard-exec.sh" << 'WRAPPER'
#!/usr/bin/env bash
# Shell replacement for AI tools — calls guard.sh in exec mode.
# Use this as $SHELL when launching AI tools directly (without execwrap).
# guard.sh alone is check-only (validator). This wrapper adds execution.
exec "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/guard.sh" --exec "$@"
WRAPPER
        make_executable "$dir/.llmsec/guard-exec.sh"
        FILES_CREATED=$((FILES_CREATED + 1))
        log_ok "Created .llmsec/guard-exec.sh"
    fi

    echo ""
    log_info "Shell wrapper installed:"
    echo -e "  ${BOLD}.llmsec/guard.sh${NC}       — check-only validator (used by execwrap Layer 2)"
    echo -e "  ${BOLD}.llmsec/guard-exec.sh${NC}  — shell replacement for direct AI tool use"
    echo ""
    log_info "To use as direct shell replacement, launch your AI tool with:"
    echo -e "  ${BOLD}SHELL=$dir/.llmsec/guard-exec.sh <your-ai-tool>${NC}"
    echo ""
}

# ============================================================================
# CLI argument parsing
# ============================================================================

show_help() {
    echo "LLM Security Toolkit - Repository Hardening"
    echo ""
    echo "Usage: harden.sh [TARGET_DIR] [OPTIONS]"
    echo ""
    echo "Arguments:"
    echo "  TARGET_DIR             Directory to harden (default: current directory)"
    echo ""
    echo "Options:"
    echo "  --tool TOOL            Target tool: claude-code, opencode, cursor, cline,"
    echo "                         windsurf, all (default: auto-detect)"
    echo "  --project NAME         Project name for audit logs (default: dir basename)"
    echo "  --no-hooks             Skip tool-specific hooks setup"
    echo "  --no-git-hooks         Skip git pre-commit/pre-push hook setup"
    echo "  --no-settings          Skip settings/config modifications"
    echo "  --with-wrapper         Also install shell wrapper"
    echo "  --dry-run              Show what would be done without doing it"
    echo "  --help                 Show this help message"
    echo ""
    echo "Examples:"
    echo "  harden.sh                          # Auto-detect tool, harden current dir"
    echo "  harden.sh /path/to/repo            # Harden specific directory"
    echo "  harden.sh --tool claude-code       # Force Claude Code setup"
    echo "  harden.sh --tool all               # Install hooks for all tools"
    echo "  harden.sh --dry-run                # Preview changes"
    echo "  harden.sh --tool all --with-wrapper  # Everything including shell wrapper"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tool)
                TOOL="$2"
                shift 2
                ;;
            --project)
                PROJECT_NAME="$2"
                shift 2
                ;;
            --no-hooks)
                SKIP_HOOKS=true
                shift
                ;;
            --no-git-hooks)
                SKIP_GIT_HOOKS=true
                shift
                ;;
            --no-settings)
                SKIP_SETTINGS=true
                shift
                ;;
            --with-wrapper)
                WITH_WRAPPER=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            -*)
                log_err "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                TARGET_DIR="$1"
                shift
                ;;
        esac
    done
}

# ============================================================================
# Main
# ============================================================================

main() {
    parse_args "$@"

    # Default target directory
    if [[ -z "$TARGET_DIR" ]]; then
        TARGET_DIR="$(pwd)"
    fi

    # Resolve to absolute path
    TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

    # Default project name
    if [[ -z "$PROJECT_NAME" ]]; then
        PROJECT_NAME="$(basename "$TARGET_DIR")"
    fi

    # Sanitize project name (alphanumeric + underscore + hyphen only)
    PROJECT_NAME=$(echo "$PROJECT_NAME" | sed 's/[^a-zA-Z0-9_-]/_/g')

    echo ""
    echo -e "${BOLD}LLM Security Toolkit - Repository Hardening${NC}"
    echo "============================================"
    echo ""
    echo "Target:  $TARGET_DIR"
    echo "Project: $PROJECT_NAME"
    $DRY_RUN && echo -e "${YELLOW}Mode:    DRY RUN (no changes will be made)${NC}"
    echo ""

    # Verify templates exist
    if [[ ! -d "$TEMPLATES_DIR" ]]; then
        log_err "Templates directory not found: $TEMPLATES_DIR"
        log_err "Make sure you're running from the llmsec project."
        exit 1
    fi

    # Auto-detect tool if not specified
    if [[ -z "$TOOL" ]]; then
        TOOL=$(detect_tool "$TARGET_DIR")
        if [[ -z "$TOOL" ]]; then
            log_warn "No AI tool config detected in $TARGET_DIR"
            log_info "Installing git hooks only (universal protection)"
            TOOL="git-only"
        else
            log_info "Auto-detected: $TOOL"
        fi
    fi

    echo ""

    # Install tool-specific hooks
    case "$TOOL" in
        claude-code)
            install_claude_code "$TARGET_DIR"
            ;;
        opencode)
            install_opencode "$TARGET_DIR"
            ;;
        cursor)
            install_cursor "$TARGET_DIR"
            ;;
        cline)
            install_cline "$TARGET_DIR"
            ;;
        windsurf)
            install_windsurf "$TARGET_DIR"
            ;;
        all)
            install_claude_code "$TARGET_DIR"
            install_opencode "$TARGET_DIR"
            install_cursor "$TARGET_DIR"
            install_cline "$TARGET_DIR"
            install_windsurf "$TARGET_DIR"
            ;;
        git-only)
            # Only git hooks, handled below
            ;;
        *)
            log_err "Unknown tool: $TOOL"
            log_err "Supported: claude-code, opencode, cursor, cline, windsurf, all"
            exit 1
            ;;
    esac

    # Install git hooks (unless skipped)
    if ! $SKIP_GIT_HOOKS; then
        echo ""
        install_git_hooks "$TARGET_DIR"
    fi

    # Install shell wrapper (if requested)
    if $WITH_WRAPPER; then
        echo ""
        install_shell_wrapper "$TARGET_DIR"
    fi

    # Summary
    echo ""
    echo -e "${BOLD}Summary${NC}"
    echo "-------"
    if $DRY_RUN; then
        echo -e "${YELLOW}Dry run complete. No files were modified.${NC}"
    else
        echo -e "Files created:  ${GREEN}$FILES_CREATED${NC}"
        echo -e "Files modified: ${GREEN}$FILES_MODIFIED${NC}"
        echo ""
        echo -e "${GREEN}Repository hardened successfully!${NC}"
    fi
    echo ""

    # Verification hints
    if ! $DRY_RUN; then
        echo -e "${BOLD}Verify:${NC}"
        case "$TOOL" in
            claude-code)
                echo "  echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"rm -rf /\"}}' | bash $TARGET_DIR/.claude/hooks/security_hook.sh"
                echo "  (Should show BLOCKED message and exit 2)"
                ;;
            cursor)
                echo "  echo '{\"command\":\"rm -rf /\"}' | bash $TARGET_DIR/.cursor/hooks/guard.sh"
                echo "  (Should output JSON with permission:deny)"
                ;;
            cline)
                echo "  echo '{\"tool_name\":\"execute_command\",\"tool_input\":{\"command\":\"rm -rf /\"}}' | bash $TARGET_DIR/.clinerules/hooks/PreToolUse"
                echo "  (Should output JSON with cancel:true)"
                ;;
        esac

        if ! $SKIP_GIT_HOOKS; then
            echo ""
            echo -e "${BOLD}Git hooks active:${NC}"
            echo "  pre-commit: scans staged Python files for dangerous patterns"
            echo "  pre-push:   blocks force pushes to protected branches"
        fi

        echo ""
        echo -e "${BOLD}Next steps:${NC}"
        echo "  1. Review the installed hooks and settings"
        echo "  2. Commit the hooks to version control: git add .githooks/ .claude/ .cursor/ etc."
        echo "  3. Share with your team so everyone gets the same protection"
        echo "  4. Customize hooks for your project's specific needs"
        echo ""
        echo "Audit logs: ~/.llmsec/logs/${PROJECT_NAME}_audit.log"
    fi
}

main "$@"
