set dotenv-load := true

# Default: show available recipes
default:
    @just --list

# =============================================================================
# Installation
# =============================================================================

# Install langywrap system-wide (builds RTK, installs package, sets up config)
install:
    @bash install.sh

# Build RTK from source and install to ~/.local/bin/rtk
install-rtk:
    @bash scripts/build_rtk.sh

# Build OpenWolf from source and install to ~/.local/bin/openwolf
install-openwolf:
    @bash scripts/build_openwolf.sh

# Install textify (LLM-free doc extraction) from the vendored submodule
install-textify:
    @bash scripts/build_textify.sh

# Install graphify (code knowledge graph) from the vendored submodule
install-graphify:
    @bash scripts/build_graphify.sh

# Couple a downstream project to langywrap
# Usage: just couple /path/to/project [--minimal|--full|--security-only]
couple path *args:
    @bash scripts/couple.sh {{path}} {{args}}

# =============================================================================
# Testing
# =============================================================================

# Run tests
test:
    uv run pytest

# Run tests (verbose)
testv:
    uv run pytest -v

# Run tests with coverage
testc:
    uv run pytest --cov=langywrap --cov-report=term-missing

# =============================================================================
# Code quality
# =============================================================================

# Lint (quiet)
lint:
    uv run ruff check -q lib/

# Lint with auto-fix
lint-fix:
    uv run ruff check --fix lib/

# Format code
fmt:
    uv run ruff format -q lib/

# Type checking
typecheck:
    uv run mypy lib/langywrap/

# Fix: lint-fix + fmt
fix: lint-fix fmt

# Validate: lint + typecheck
validate: lint typecheck

# Check: lint + typecheck + test
check: lint typecheck test

# Dev: fix + check (full local cycle)
dev: fix check

# =============================================================================
# Environment
# =============================================================================

# Sync dependencies
sync:
    uv sync

# Run ralph dry-run (validate loop config without executing)
ralph-dry:
    langywrap ralph dry-run

# =============================================================================
# Cleanup
# =============================================================================

# Remove build artifacts and caches
clean:
    @find . -type d -name "__pycache__" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name ".mypy_cache" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name ".ruff_cache" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
    @find . -type d -name "*.egg-info" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
    @find . -type f -name "*.pyc" -not -path "./.git/*" -delete 2>/dev/null || true
    @echo "Clean."

# Remove RTK build artifacts (forces rebuild on next install-rtk)
clean-rtk:
    @rm -rf rtk/target
    @echo "RTK build artifacts removed."

# Remove OpenWolf build artifacts (forces rebuild on next install-openwolf)
clean-openwolf:
    @rm -rf openwolf/dist openwolf/node_modules
    @echo "OpenWolf build artifacts removed."
