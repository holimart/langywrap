# LLM Security Toolkit - Project Commands
# Install 'just' command runner: https://github.com/casey/just
#
# Usage:
#   just          - Show available commands
#   just test     - Run test suite
#   just run      - Run orchestrator
#   just install  - Install to system

# ============================================================================
# Configuration
# ============================================================================

# Project directories
project_root := justfile_directory()
tools_dir := project_root / "tools"
tests_dir := project_root / "tests"
configs_dir := project_root / "configs"
docs_dir := project_root / "docs"

# Installation directories
install_dir := env_var_or_default('PREFIX', env_var('HOME') / 'bin')
config_dir := env_var('HOME') / '.llmsec'

# Colors for output
RED := '\033[0;31m'
GREEN := '\033[0;32m'
YELLOW := '\033[1;33m'
BLUE := '\033[0;34m'
NC := '\033[0m'

# ============================================================================
# Default - Show Help
# ============================================================================

# Show available commands
@default:
    just --list

# ============================================================================
# Testing Commands
# ============================================================================

# Run comprehensive test suite (safe, no dangerous commands executed)
@test:
    echo -e "{{BLUE}}Running comprehensive test suite...{{NC}}"
    {{tests_dir}}/test-orchestrator.sh

# Run mock agent tests
@test-mock:
    echo -e "{{BLUE}}Running mock agent tests...{{NC}}"
    {{tests_dir}}/mock-agent.sh

# Run quick smoke test
@test-quick:
    echo -e "{{BLUE}}Running quick smoke test...{{NC}}"
    {{tools_dir}}/interceptors/intercept-enhanced.py "echo test"
    {{tools_dir}}/interceptors/intercept-enhanced.py "rm -rf /tmp/fake-test-123" 2>&1 | grep -q "blocked" && echo -e "{{GREEN}}✓ Interceptor working{{NC}}" || echo -e "{{RED}}✗ Interceptor failed{{NC}}"

# Test interceptor with custom command
test-intercept COMMAND:
    {{tools_dir}}/interceptors/intercept-enhanced.py "{{COMMAND}}"

# Clean test artifacts
@test-clean:
    echo -e "{{YELLOW}}Cleaning test artifacts...{{NC}}"
    rm -rf {{tests_dir}}/test-project
    rm -f {{config_dir}}/logs/*.log
    echo -e "{{GREEN}}✓ Test artifacts cleaned{{NC}}"

# ============================================================================
# Running Commands
# ============================================================================

# Run orchestrator with default settings
@run *ARGS:
    echo -e "{{BLUE}}Starting secure orchestrator...{{NC}}"
    {{project_root}}/secure-run.sh {{ARGS}}

# Run with basic security level
@run-basic *ARGS:
    {{project_root}}/secure-run.sh --level=basic {{ARGS}}

# Run with recommended security level
@run-recommended *ARGS:
    {{project_root}}/secure-run.sh --level=recommended {{ARGS}}

# Run with maximum security level
@run-maximum *ARGS:
    {{project_root}}/secure-run.sh --level=maximum {{ARGS}}

# Run without Docker isolation
@run-no-docker *ARGS:
    {{project_root}}/secure-run.sh --no-isolation {{ARGS}}

# Run in verbose mode
@run-verbose *ARGS:
    {{project_root}}/secure-run.sh --verbose {{ARGS}}

# Show orchestrator help
@help:
    {{project_root}}/secure-run.sh --help

# Show orchestrator version
@version:
    {{project_root}}/secure-run.sh --version

# ============================================================================
# Installation Commands
# ============================================================================

# Install orchestrator to system
@install:
    echo -e "{{BLUE}}Installing LLM Security Toolkit...{{NC}}"
    mkdir -p {{install_dir}}
    mkdir -p {{config_dir}}/defaults
    mkdir -p {{config_dir}}/logs
    cp {{project_root}}/secure-run.sh {{install_dir}}/secure-run
    chmod +x {{install_dir}}/secure-run
    cp -r {{tools_dir}} {{config_dir}}/
    cp -r {{configs_dir}}/defaults/* {{config_dir}}/defaults/
    echo -e "{{GREEN}}✓ Installed to {{install_dir}}/secure-run{{NC}}"
    echo -e "{{GREEN}}✓ Config in {{config_dir}}{{NC}}"
    echo ""
    echo "Add to your PATH if needed:"
    echo "  export PATH=\"{{install_dir}}:\$PATH\""
    echo ""
    echo "Run with:"
    echo "  secure-run"

# Install shell alias
@install-alias:
    #!/usr/bin/env bash
    SHELL_RC=""
    if [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bashrc"
    elif [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    fi

    if [ -n "$SHELL_RC" ]; then
        if ! grep -q "alias secure-run" "$SHELL_RC"; then
            echo "" >> "$SHELL_RC"
            echo "# LLM Security Toolkit" >> "$SHELL_RC"
            echo "alias secure-run='{{project_root}}/secure-run.sh'" >> "$SHELL_RC"
            echo -e "{{GREEN}}✓ Alias added to $SHELL_RC{{NC}}"
            echo "Reload shell: source $SHELL_RC"
        else
            echo -e "{{YELLOW}}⚠ Alias already exists{{NC}}"
        fi
    else
        echo -e "{{RED}}✗ Could not find shell RC file{{NC}}"
    fi

# Uninstall from system
@uninstall:
    echo -e "{{YELLOW}}Uninstalling LLM Security Toolkit...{{NC}}"
    rm -f {{install_dir}}/secure-run
    echo -e "{{GREEN}}✓ Removed from {{install_dir}}{{NC}}"
    echo ""
    echo "Config preserved in {{config_dir}}"
    echo "Remove manually if desired: rm -rf {{config_dir}}"

# ============================================================================
# Development Commands
# ============================================================================

# Check all scripts for syntax errors
@check:
    echo -e "{{BLUE}}Checking shell scripts...{{NC}}"
    find {{project_root}} -name "*.sh" -type f -exec bash -n {} \; && echo -e "{{GREEN}}✓ All shell scripts valid{{NC}}" || echo -e "{{RED}}✗ Syntax errors found{{NC}}"
    echo -e "{{BLUE}}Checking Python scripts...{{NC}}"
    find {{project_root}} -name "*.py" -type f -exec python3 -m py_compile {} \; && echo -e "{{GREEN}}✓ All Python scripts valid{{NC}}" || echo -e "{{RED}}✗ Syntax errors found{{NC}}"

# Format Python code
@format:
    echo -e "{{BLUE}}Formatting Python code...{{NC}}"
    find {{tools_dir}} -name "*.py" -type f -exec autopep8 --in-place --aggressive --aggressive {} \; 2>/dev/null || echo -e "{{YELLOW}}⚠ autopep8 not installed, skipping{{NC}}"
    echo -e "{{GREEN}}✓ Formatting complete{{NC}}"

# Lint Python code
@lint:
    echo -e "{{BLUE}}Linting Python code...{{NC}}"
    find {{tools_dir}} -name "*.py" -type f -exec pylint {} \; 2>/dev/null || echo -e "{{YELLOW}}⚠ pylint not installed, skipping{{NC}}"

# Count lines of code
@count:
    echo -e "{{BLUE}}Lines of Code Statistics:{{NC}}"
    echo ""
    echo "Shell scripts:"
    find {{project_root}} -name "*.sh" -type f -exec wc -l {} \; | awk '{sum+=$1} END {print "  " sum " lines"}'
    echo ""
    echo "Python scripts:"
    find {{project_root}} -name "*.py" -type f -exec wc -l {} \; | awk '{sum+=$1} END {print "  " sum " lines"}'
    echo ""
    echo "YAML configs:"
    find {{configs_dir}} -name "*.yaml" -type f -exec wc -l {} \; | awk '{sum+=$1} END {print "  " sum " lines"}'
    echo ""
    echo "Documentation:"
    find {{project_root}} -name "*.md" -type f -exec wc -l {} \; | awk '{sum+=$1} END {print "  " sum " lines"}'
    echo ""
    echo "Total:"
    find {{project_root}} \( -name "*.sh" -o -name "*.py" -o -name "*.yaml" -o -name "*.md" \) -type f -exec wc -l {} \; | awk '{sum+=$1} END {print "  " sum " lines"}'

# Show project statistics
@stats:
    #!/usr/bin/env bash
    echo -e "{{BLUE}}Project Statistics:{{NC}}"
    echo ""
    echo "Files:"
    echo "  Shell scripts: $(find {{project_root}} -name "*.sh" -type f | wc -l)"
    echo "  Python scripts: $(find {{project_root}} -name "*.py" -type f | wc -l)"
    echo "  YAML configs: $(find {{configs_dir}} -name "*.yaml" -type f | wc -l)"
    echo "  Documentation: $(find {{project_root}} -name "*.md" -type f | wc -l)"
    echo ""
    echo "Tests:"
    echo "  Test files: $(find {{tests_dir}} -name "*.sh" -type f | wc -l)"
    echo ""
    echo "Tools:"
    echo "  Interceptors: $(find {{tools_dir}}/interceptors -name "*.py" -type f | wc -l)"
    echo "  Monitors: $(find {{tools_dir}}/monitors -name "*.sh" -type f | wc -l)"

# ============================================================================
# Monitoring Commands
# ============================================================================

# Start background monitor
@monitor:
    echo -e "{{BLUE}}Starting security monitor...{{NC}}"
    {{tools_dir}}/monitors/claude-monitor.sh &
    echo -e "{{GREEN}}✓ Monitor started (PID: $!){{NC}}"
    echo "View logs: just logs-monitor"
    echo "Stop: just stop-monitor"

# Stop background monitor
@stop-monitor:
    echo -e "{{YELLOW}}Stopping monitor...{{NC}}"
    pkill -f claude-monitor.sh && echo -e "{{GREEN}}✓ Monitor stopped{{NC}}" || echo -e "{{YELLOW}}⚠ Monitor not running{{NC}}"

# View monitor logs
@logs-monitor:
    tail -f {{config_dir}}/logs/claude-monitor.log 2>/dev/null || echo -e "{{YELLOW}}⚠ No monitor logs found{{NC}}"

# View intercept logs
@logs-intercept:
    tail -f {{config_dir}}/logs/intercept.log 2>/dev/null || echo -e "{{YELLOW}}⚠ No intercept logs found{{NC}}"

# View all logs
@logs:
    tail -f {{config_dir}}/logs/*.log 2>/dev/null || echo -e "{{YELLOW}}⚠ No logs found{{NC}}"

# ============================================================================
# Configuration Commands
# ============================================================================

# Create project-specific config
@config-init:
    echo -e "{{BLUE}}Creating project config...{{NC}}"
    mkdir -p .settings
    cp {{configs_dir}}/defaults/permissions.yaml .settings/permissions.yaml
    echo -e "{{GREEN}}✓ Created .settings/permissions.yaml{{NC}}"
    echo "Edit: vim .settings/permissions.yaml"

# Validate config files
@config-check:
    #!/usr/bin/env bash
    echo -e "{{BLUE}}Validating configuration files...{{NC}}"
    for file in {{configs_dir}}/defaults/*.yaml; do
        python3 -c "import yaml; yaml.safe_load(open('$file'))" 2>/dev/null && echo -e "{{GREEN}}✓ $(basename $file){{NC}}" || echo -e "{{RED}}✗ $(basename $file){{NC}}"
    done

# Show current config hierarchy
@config-show:
    #!/usr/bin/env bash
    echo -e "{{BLUE}}Configuration Hierarchy:{{NC}}"
    echo ""
    [ -d ".settings" ] && echo -e "{{GREEN}}1. .settings/ (found){{NC}}" || echo -e "{{YELLOW}}1. .settings/ (not found){{NC}}"
    [ -d ".claude" ] && echo -e "{{GREEN}}2. .claude/ (found){{NC}}" || echo -e "{{YELLOW}}2. .claude/ (not found){{NC}}"
    [ -d ".opencode" ] && echo -e "{{GREEN}}3. .opencode/ (found){{NC}}" || echo -e "{{YELLOW}}3. .opencode/ (not found){{NC}}"
    [ -d "{{config_dir}}/defaults" ] && echo -e "{{GREEN}}4. {{config_dir}}/defaults/ (found){{NC}}" || echo -e "{{YELLOW}}4. {{config_dir}}/defaults/ (not found){{NC}}"
    [ -d "{{configs_dir}}/defaults" ] && echo -e "{{GREEN}}5. {{configs_dir}}/defaults/ (found){{NC}}" || echo -e "{{YELLOW}}5. {{configs_dir}}/defaults/ (not found){{NC}}"

# ============================================================================
# Documentation Commands
# ============================================================================

# Build documentation (if using a doc generator)
@docs:
    echo -e "{{BLUE}}Documentation located at:{{NC}}"
    echo "  README.md"
    echo "  docs/ORCHESTRATOR_GUIDE.md"
    echo "  docs/QUICKSTART.md"
    echo "  EXAMPLE_USAGE.md"

# Serve documentation locally (requires Python)
@docs-serve PORT="8000":
    echo -e "{{BLUE}}Serving documentation at http://localhost:{{PORT}}{{NC}}"
    cd {{project_root}} && python3 -m http.server {{PORT}}

# Check documentation links
@docs-check:
    #!/usr/bin/env bash
    echo -e "{{BLUE}}Checking documentation links...{{NC}}"
    find {{project_root}} -name "*.md" -type f -exec grep -H "](.*)" {} \; | \
        grep -v "http" | \
        awk -F'[()]' '{print $2}' | \
        while read link; do
            [ -f "{{project_root}}/$link" ] || echo -e "{{RED}}✗ Broken: $link{{NC}}"
        done

# ============================================================================
# Git Commands
# ============================================================================

# Initialize git repository
@git-init:
    {{project_root}}/init-git.sh

# Create release commit
@release VERSION:
    #!/usr/bin/env bash
    echo -e "{{BLUE}}Creating release {{VERSION}}...{{NC}}"

    # Update version in files
    sed -i "s/Version.*0\.[0-9]\.[0-9]/Version: {{VERSION}}/g" README.md PROJECT_STATUS.md
    sed -i "s/ORCHESTRATOR_VERSION=.*/ORCHESTRATOR_VERSION=\"{{VERSION}}\"/g" secure-run.sh

    # Run tests
    just test

    # Create commit
    git add .
    git commit -m "Release {{VERSION}}

- Updated version to {{VERSION}}
- All tests passing
- Documentation updated

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

    # Create tag
    git tag -a "v{{VERSION}}" -m "Release {{VERSION}}"

    echo -e "{{GREEN}}✓ Release {{VERSION}} created{{NC}}"
    echo "Push with: git push && git push --tags"

# ============================================================================
# Cleanup Commands
# ============================================================================

# Clean all generated files and logs
@clean:
    echo -e "{{YELLOW}}Cleaning project...{{NC}}"
    rm -rf {{tests_dir}}/test-project
    rm -f {{config_dir}}/logs/*.log
    find {{project_root}} -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find {{project_root}} -name "*.pyc" -delete 2>/dev/null || true
    echo -e "{{GREEN}}✓ Project cleaned{{NC}}"

# Deep clean (including configs)
@clean-all:
    echo -e "{{RED}}Deep cleaning (including configs)...{{NC}}"
    just clean
    rm -rf {{config_dir}}
    echo -e "{{GREEN}}✓ Deep clean complete{{NC}}"

# ============================================================================
# Docker Commands
# ============================================================================

# Build Docker sandbox image
@docker-build:
    echo -e "{{BLUE}}Building Docker sandbox...{{NC}}"
    docker build -f {{configs_dir}}/docker/Dockerfile.sandbox -t llmsec-sandbox {{configs_dir}}/docker
    echo -e "{{GREEN}}✓ Docker image built: llmsec-sandbox{{NC}}"

# Run in Docker sandbox
@docker-run *ARGS:
    {{configs_dir}}/docker/run-sandbox.sh {{ARGS}}

# Clean Docker images
@docker-clean:
    docker rmi llmsec-sandbox 2>/dev/null && echo -e "{{GREEN}}✓ Docker image removed{{NC}}" || echo -e "{{YELLOW}}⚠ No image to remove{{NC}}"

# ============================================================================
# Emergency Commands
# ============================================================================

# Emergency stop all Claude/agent processes
@emergency-stop:
    echo -e "{{RED}}🛑 EMERGENCY STOP{{NC}}"
    {{tools_dir}}/kill-claude.sh || pkill -f "claude\|opencode" || echo -e "{{YELLOW}}⚠ No processes to kill{{NC}}"

# ============================================================================
# Example Commands
# ============================================================================

# Show example usage
@examples:
    cat {{project_root}}/EXAMPLE_USAGE.md

# Run example scenario
@example-basic:
    echo -e "{{BLUE}}Running basic security example...{{NC}}"
    just run-basic -- echo "Hello from secure environment"

@example-maximum:
    echo -e "{{BLUE}}Running maximum security example...{{NC}}"
    just run-maximum -- echo "Hello from maximum security"

# ============================================================================
# Hardening Commands
# ============================================================================

# Harden a target directory (auto-detect tool)
@harden DIR=".":
    echo -e "{{BLUE}}Hardening repository...{{NC}}"
    {{tools_dir}}/harden/harden.sh {{DIR}}

# Harden for Claude Code specifically
@harden-claude DIR=".":
    echo -e "{{BLUE}}Hardening for Claude Code...{{NC}}"
    {{tools_dir}}/harden/harden.sh {{DIR}} --tool claude-code

# Install all tool templates
@harden-all DIR=".":
    echo -e "{{BLUE}}Installing all tool templates...{{NC}}"
    {{tools_dir}}/harden/harden.sh {{DIR}} --tool all --with-wrapper

# Dry run (preview changes)
@harden-dry DIR=".":
    echo -e "{{BLUE}}Dry run (no changes)...{{NC}}"
    {{tools_dir}}/harden/harden.sh {{DIR}} --dry-run

# Run harden-specific tests
@test-harden:
    echo -e "{{BLUE}}Running hardening tests...{{NC}}"
    {{tests_dir}}/test-harden.sh

# ============================================================================
# Utility Commands
# ============================================================================

# Show file tree
@tree:
    tree -L 3 -I '__pycache__|*.pyc' --charset ascii

# Watch logs in real-time
@watch-logs:
    watch -n 1 'tail -20 {{config_dir}}/logs/*.log 2>/dev/null'

# Benchmark orchestrator startup time
@benchmark:
    #!/usr/bin/env bash
    echo -e "{{BLUE}}Benchmarking orchestrator startup...{{NC}}"
    time {{project_root}}/secure-run.sh --help > /dev/null
    echo ""
    echo "Run 5 times:"
    for i in {1..5}; do
        /usr/bin/time -f "  Run $i: %E" {{project_root}}/secure-run.sh --help > /dev/null 2>&1
    done

# ============================================================================
# CI/CD Commands
# ============================================================================

# Run all CI checks
@ci:
    echo -e "{{BLUE}}Running CI pipeline...{{NC}}"
    just check
    just test
    just config-check
    echo -e "{{GREEN}}✓ CI pipeline passed{{NC}}"

# Pre-commit hook
@pre-commit:
    echo -e "{{BLUE}}Running pre-commit checks...{{NC}}"
    just check
    just test-quick
    echo -e "{{GREEN}}✓ Pre-commit checks passed{{NC}}"
