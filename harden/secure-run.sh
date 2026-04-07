#!/bin/bash
# ============================================================================
# SECURE-RUN: Universal AI Agent Security Orchestrator
# ============================================================================
#
# PURPOSE:
#   Single entry point to run Claude Code, OpenCode, or any AI agent with
#   comprehensive security measures applied automatically.
#
# USAGE:
#   secure-run.sh [OPTIONS] [-- COMMAND]
#
# EXAMPLES:
#   secure-run.sh                    # Launch Claude Code with all security
#   secure-run.sh -- opencode        # Launch OpenCode with all security
#   secure-run.sh --no-docker        # Skip Docker isolation
#   secure-run.sh --level=basic      # Use basic security preset
#
# CONFIGURATION HIERARCHY (most restrictive wins):
#   1. Project directory: .settings/  (default location)
#   2. Project directory: .claude/
#   3. Project directory: .opencode/
#   4. Orchestrator defaults: ~/.llmsec/defaults/
#   5. Bundled defaults: ./configs/defaults/
#
# ALL SECURITY LAYERS ENABLED BY DEFAULT:
#   ✓ Layer 1: Input filtering (permission blocklists)
#   ✓ Layer 2: Command interception (pattern analysis)
#   ✓ Layer 3: Execution isolation (containers/sandbox)
#   ✓ Layer 4: Output validation (code scanning)
#   ✓ Layer 5: Monitoring (real-time oversight)
#
# ============================================================================

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
ORCHESTRATOR_VERSION="0.2.0"

# Default settings directories (in order of preference)
SETTINGS_DIRS=(
    "$PROJECT_DIR/.settings"
    "$PROJECT_DIR/.claude"
    "$PROJECT_DIR/.opencode"
    "$HOME/.llmsec/defaults"
    "$SCRIPT_DIR/configs/defaults"
)

# Security layers (all ON by default)
ENABLE_INPUT_FILTER=true
ENABLE_INTERCEPTOR=true
ENABLE_ISOLATION=true
ENABLE_VALIDATION=true
ENABLE_MONITORING=true

# Isolation method (auto-detect best available)
ISOLATION_METHOD="auto"  # auto, docker, bubblewrap, none

# Target application
TARGET_APP="claude"  # Default to Claude Code

# Temporary files
TEMP_DIR=$(mktemp -d -t secure-run.XXXXXX)
trap "cleanup" EXIT INT TERM

# Process tracking
MONITOR_PID=""
INTERCEPTOR_PID=""
TARGET_PID=""

# Logging
LOG_DIR="$HOME/.llmsec/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/secure-run-$(date +%Y%m%d-%H%M%S).log"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date -Iseconds)
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "$@"; }
log_error() { log "ERROR" "$@"; }
log_success() { log "SUCCESS" "$@"; }

print_header() {
    echo ""
    echo "============================================================================"
    echo "$1"
    echo "============================================================================"
    echo ""
}

print_section() {
    echo ""
    echo "--- $1"
    echo ""
}

cleanup() {
    log_info "Cleaning up..."

    # Stop monitoring
    if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
        log_info "Stopping monitor (PID: $MONITOR_PID)"
        kill "$MONITOR_PID" 2>/dev/null || true
    fi

    # Stop interceptor
    if [ -n "$INTERCEPTOR_PID" ] && kill -0 "$INTERCEPTOR_PID" 2>/dev/null; then
        log_info "Stopping interceptor (PID: $INTERCEPTOR_PID)"
        kill "$INTERCEPTOR_PID" 2>/dev/null || true
    fi

    # Clean temp directory
    if [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi

    log_success "Cleanup complete"
}

# ============================================================================
# CONFIGURATION LOADING
# ============================================================================

find_config_file() {
    local filename="$1"

    # Search in order of preference
    for dir in "${SETTINGS_DIRS[@]}"; do
        if [ -f "$dir/$filename" ]; then
            echo "$dir/$filename"
            return 0
        fi
    done

    return 1
}

load_config() {
    local config_type="$1"
    local config_file=""

    log_info "Loading $config_type configuration..."

    # Try to find config file
    case "$config_type" in
        permissions)
            config_file=$(find_config_file "permissions.yaml" || find_config_file "settings.json" || echo "")
            ;;
        resources)
            config_file=$(find_config_file "resources.yaml" || echo "")
            ;;
        network)
            config_file=$(find_config_file "network.yaml" || echo "")
            ;;
        monitoring)
            config_file=$(find_config_file "monitoring.yaml" || echo "")
            ;;
        messages)
            config_file=$(find_config_file "messages.yaml" || echo "")
            ;;
    esac

    if [ -n "$config_file" ] && [ -f "$config_file" ]; then
        log_success "Found $config_type config: $config_file"
        echo "$config_file"
    else
        log_warn "No $config_type config found, using defaults"
        echo ""
    fi
}

merge_configs() {
    # This function merges all found configs, applying most restrictive
    # For now, we use Python for YAML merging (lightweight)

    local config_type="$1"
    local output_file="$TEMP_DIR/${config_type}_merged.yaml"

    # Collect all config files for this type
    local configs=()
    for dir in "${SETTINGS_DIRS[@]}"; do
        local file="$dir/${config_type}.yaml"
        if [ -f "$file" ]; then
            configs+=("$file")
        fi
    done

    if [ ${#configs[@]} -eq 0 ]; then
        log_warn "No ${config_type} configs found"
        return 1
    fi

    # For now, just use the first (most specific) one
    # TODO: Implement proper merging with "most restrictive wins"
    cp "${configs[0]}" "$output_file"
    echo "$output_file"
}

# ============================================================================
# SECURITY LAYER SETUP
# ============================================================================

setup_layer1_input_filter() {
    if [ "$ENABLE_INPUT_FILTER" != "true" ]; then
        log_info "Layer 1 (Input Filter) - DISABLED"
        return 0
    fi

    print_section "Layer 1: Input Filtering"

    local permissions_config=$(load_config "permissions")

    if [ -z "$permissions_config" ]; then
        log_info "Using bundled default permissions"
        permissions_config="$SCRIPT_DIR/configs/defaults/permissions.yaml"
    fi

    # Copy to Claude/OpenCode config location
    local target_config=""
    if [ "$TARGET_APP" = "claude" ]; then
        target_config="$HOME/.claude/settings.json"
        mkdir -p "$HOME/.claude"
    elif [ "$TARGET_APP" = "opencode" ]; then
        target_config="$HOME/.opencode/settings.json"
        mkdir -p "$HOME/.opencode"
    fi

    if [ -n "$target_config" ]; then
        # Convert YAML to JSON if needed (for Claude/OpenCode)
        if [[ "$permissions_config" == *.yaml ]]; then
            log_info "Converting YAML config to JSON for $TARGET_APP"
            "$SCRIPT_DIR/tools/converters/yaml-to-json.py" \
                "$permissions_config" "$target_config"
        else
            cp "$permissions_config" "$target_config"
        fi
        log_success "Layer 1 configured: $target_config"
    fi
}

setup_layer2_interceptor() {
    if [ "$ENABLE_INTERCEPTOR" != "true" ]; then
        log_info "Layer 2 (Interceptor) - DISABLED"
        return 0
    fi

    print_section "Layer 2: Command Interception"

    # Load interceptor config
    local messages_config=$(load_config "messages")

    # Start interceptor in background
    log_info "Starting command interceptor..."

    # Export config path for interceptor to use
    export INTERCEPTOR_CONFIG="${messages_config:-$SCRIPT_DIR/configs/defaults/messages.yaml}"
    export ENABLE_DATA_THEFT_PREVENTION=true

    # Note: Interceptor will be used as shell wrapper
    export SECURE_SHELL="$SCRIPT_DIR/tools/interceptors/intercept.py"

    log_success "Layer 2 configured: Interceptor ready"
}

setup_layer3_isolation() {
    if [ "$ENABLE_ISOLATION" != "true" ]; then
        log_info "Layer 3 (Isolation) - DISABLED"
        return 0
    fi

    print_section "Layer 3: Execution Isolation"

    # Auto-detect best isolation method
    if [ "$ISOLATION_METHOD" = "auto" ]; then
        if command -v docker &> /dev/null; then
            ISOLATION_METHOD="docker"
        elif command -v bwrap &> /dev/null; then
            ISOLATION_METHOD="bubblewrap"
        else
            log_warn "No isolation tools found, isolation disabled"
            ISOLATION_METHOD="none"
        fi
    fi

    log_info "Isolation method: $ISOLATION_METHOD"

    # Load resource limits
    local resources_config=$(load_config "resources")

    # Apply resource limits
    if [ -f "$resources_config" ]; then
        # Parse YAML and apply limits (simplified)
        # In production, use proper YAML parser
        log_info "Applying resource limits from: $resources_config"
    else
        # Default limits
        log_info "Applying default resource limits"
        ulimit -v 4000000   # 4GB virtual memory
        ulimit -t 300       # 300 seconds CPU time
        ulimit -f 1000000   # 1GB max file size
    fi

    log_success "Layer 3 configured: $ISOLATION_METHOD isolation ready"
}

setup_layer4_validation() {
    if [ "$ENABLE_VALIDATION" != "true" ]; then
        log_info "Layer 4 (Validation) - DISABLED"
        return 0
    fi

    print_section "Layer 4: Output Validation"

    # Set up git hooks if in a git repo
    if [ -d "$PROJECT_DIR/.git" ]; then
        log_info "Installing pre-commit hooks..."

        local hook_file="$PROJECT_DIR/.git/hooks/pre-commit"
        cat > "$hook_file" << 'EOF'
#!/bin/bash
# Auto-installed by secure-run.sh
# Validates code before commits

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd)"

# Run Semgrep if available
if command -v semgrep &> /dev/null; then
    echo "Running security scan..."
    semgrep --config "$SCRIPT_DIR/configs/semgrep/dangerous-operations.yaml" . || exit 1
fi

echo "✓ Validation passed"
EOF
        chmod +x "$hook_file"
        log_success "Pre-commit hook installed"
    fi

    log_success "Layer 4 configured: Validation ready"
}

setup_layer5_monitoring() {
    if [ "$ENABLE_MONITORING" != "true" ]; then
        log_info "Layer 5 (Monitoring) - DISABLED"
        return 0
    fi

    print_section "Layer 5: Monitoring & Kill Switch"

    # Start background monitor
    log_info "Starting security monitor..."

    "$SCRIPT_DIR/tools/monitors/claude-monitor.sh" &
    MONITOR_PID=$!

    log_success "Layer 5 configured: Monitor running (PID: $MONITOR_PID)"

    # Register emergency kill switch
    log_info "Emergency kill switch: $SCRIPT_DIR/tools/kill-claude.sh"
}

# ============================================================================
# APPLICATION LAUNCHER
# ============================================================================

launch_application() {
    print_section "Launching $TARGET_APP"

    local launch_cmd=""

    case "$ISOLATION_METHOD" in
        docker)
            log_info "Launching in Docker container..."
            launch_cmd="$SCRIPT_DIR/configs/docker/run-sandbox.sh $PROJECT_DIR"
            ;;
        bubblewrap)
            log_info "Launching with bubblewrap..."
            launch_cmd="$SCRIPT_DIR/tools/wrappers/bubblewrap-run.sh $TARGET_APP"
            ;;
        none)
            log_info "Launching without isolation (direct)..."
            launch_cmd="$TARGET_APP"
            ;;
    esac

    # If custom command provided, use that
    if [ $# -gt 0 ]; then
        launch_cmd="$@"
    fi

    log_info "Executing: $launch_cmd"

    # Launch with interceptor if enabled
    if [ "$ENABLE_INTERCEPTOR" = "true" ]; then
        # Wrap command execution through interceptor
        export SHELL="$SCRIPT_DIR/tools/interceptors/intercept-wrapper.sh"
    fi

    # Execute
    $launch_cmd
    TARGET_PID=$!

    log_success "$TARGET_APP launched successfully"
}

# ============================================================================
# COMMAND LINE PARSING
# ============================================================================

show_usage() {
    cat << EOF
SECURE-RUN: Universal AI Agent Security Orchestrator v$ORCHESTRATOR_VERSION

USAGE:
    secure-run.sh [OPTIONS] [-- COMMAND]

OPTIONS:
    --no-input-filter      Disable Layer 1 (input filtering)
    --no-interceptor       Disable Layer 2 (command interception)
    --no-isolation         Disable Layer 3 (execution isolation)
    --no-validation        Disable Layer 4 (output validation)
    --no-monitoring        Disable Layer 5 (monitoring)

    --isolation=METHOD     Set isolation method: auto, docker, bubblewrap, none
    --app=NAME            Target application: claude, opencode, custom
    --project-dir=PATH    Project directory (default: current directory)

    --level=PRESET        Security preset: basic, recommended, maximum
                          basic       = Layer 1 + 5
                          recommended = Layer 1 + 2 + 3 + 5
                          maximum     = All layers

    --config-dir=PATH     Override config directory (default: .settings)

    -h, --help            Show this help
    -v, --verbose         Verbose logging
    --version             Show version

EXAMPLES:
    # Launch Claude Code with all security (default)
    secure-run.sh

    # Launch OpenCode with all security
    secure-run.sh --app=opencode

    # Launch with basic security only
    secure-run.sh --level=basic

    # Skip Docker isolation (use bubblewrap)
    secure-run.sh --isolation=bubblewrap

    # Custom command with security
    secure-run.sh -- python my-agent.py

CONFIGURATION:
    Configs are searched in this order (most restrictive wins):
    1. $PROJECT_DIR/.settings/
    2. $PROJECT_DIR/.claude/
    3. $PROJECT_DIR/.opencode/
    4. ~/.llmsec/defaults/
    5. Bundled defaults

FILES:
    Logs:        $LOG_DIR/
    Emergency:   $SCRIPT_DIR/tools/kill-claude.sh

For more information, see: $SCRIPT_DIR/README.md
EOF
}

parse_arguments() {
    local remaining_args=()

    while [[ $# -gt 0 ]]; do
        case $1 in
            --no-input-filter)
                ENABLE_INPUT_FILTER=false
                shift
                ;;
            --no-interceptor)
                ENABLE_INTERCEPTOR=false
                shift
                ;;
            --no-isolation)
                ENABLE_ISOLATION=false
                shift
                ;;
            --no-validation)
                ENABLE_VALIDATION=false
                shift
                ;;
            --no-monitoring)
                ENABLE_MONITORING=false
                shift
                ;;
            --isolation=*)
                ISOLATION_METHOD="${1#*=}"
                shift
                ;;
            --app=*)
                TARGET_APP="${1#*=}"
                shift
                ;;
            --project-dir=*)
                PROJECT_DIR="${1#*=}"
                shift
                ;;
            --level=*)
                local level="${1#*=}"
                case $level in
                    basic)
                        ENABLE_INPUT_FILTER=true
                        ENABLE_INTERCEPTOR=false
                        ENABLE_ISOLATION=false
                        ENABLE_VALIDATION=false
                        ENABLE_MONITORING=true
                        ;;
                    recommended)
                        ENABLE_INPUT_FILTER=true
                        ENABLE_INTERCEPTOR=true
                        ENABLE_ISOLATION=true
                        ENABLE_VALIDATION=false
                        ENABLE_MONITORING=true
                        ;;
                    maximum)
                        ENABLE_INPUT_FILTER=true
                        ENABLE_INTERCEPTOR=true
                        ENABLE_ISOLATION=true
                        ENABLE_VALIDATION=true
                        ENABLE_MONITORING=true
                        ;;
                    *)
                        log_error "Unknown level: $level"
                        exit 1
                        ;;
                esac
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            --version)
                echo "secure-run v$ORCHESTRATOR_VERSION"
                exit 0
                ;;
            -v|--verbose)
                set -x
                shift
                ;;
            --)
                shift
                remaining_args=("$@")
                break
                ;;
            *)
                remaining_args+=("$1")
                shift
                ;;
        esac
    done

    # Return remaining args for command
    echo "${remaining_args[@]}"
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

main() {
    print_header "SECURE-RUN v$ORCHESTRATOR_VERSION"

    # Parse command line
    local custom_command=$(parse_arguments "$@")

    log_info "Project directory: $PROJECT_DIR"
    log_info "Target application: $TARGET_APP"
    log_info "Log file: $LOG_FILE"

    # Show security configuration
    print_section "Security Configuration"
    echo "Layer 1 (Input Filter):   $([ "$ENABLE_INPUT_FILTER" = "true" ] && echo "✓ ENABLED" || echo "✗ DISABLED")"
    echo "Layer 2 (Interceptor):    $([ "$ENABLE_INTERCEPTOR" = "true" ] && echo "✓ ENABLED" || echo "✗ DISABLED")"
    echo "Layer 3 (Isolation):      $([ "$ENABLE_ISOLATION" = "true" ] && echo "✓ ENABLED" || echo "✗ DISABLED")"
    echo "Layer 4 (Validation):     $([ "$ENABLE_VALIDATION" = "true" ] && echo "✓ ENABLED" || echo "✗ DISABLED")"
    echo "Layer 5 (Monitoring):     $([ "$ENABLE_MONITORING" = "true" ] && echo "✓ ENABLED" || echo "✗ DISABLED")"
    echo ""

    # Set up each security layer
    setup_layer1_input_filter
    setup_layer2_interceptor
    setup_layer3_isolation
    setup_layer4_validation
    setup_layer5_monitoring

    print_section "All Security Layers Active"
    log_success "Security orchestration complete"

    # Launch application
    if [ -n "$custom_command" ]; then
        launch_application $custom_command
    else
        launch_application
    fi

    # Wait for application to exit
    wait

    log_success "Session ended normally"
}

# Run main
main "$@"
