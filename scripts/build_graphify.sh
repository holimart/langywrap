#!/usr/bin/env bash
# =============================================================================
# Install graphify from the vendored submodule (editable)
# =============================================================================
# Installs the graphify submodule into langywrap's uv environment as an
# editable dependency. The submodule is pinned (see .gitmodules); bump via
# git submodule update --remote graphify && commit.
#
# Usage: ./scripts/build_graphify.sh [--dry-run]
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}[ok]${NC}    $*"; }
info() { echo -e "${CYAN}[info]${NC}  $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANGYWRAP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GRAPHIFY_DIR="$LANGYWRAP_ROOT/graphify"

echo -e "${BOLD}${CYAN}Installing Graphify (editable, from submodule)${NC}"

command -v uv &>/dev/null || die "uv not found — install from https://docs.astral.sh/uv/"

[[ -d "$GRAPHIFY_DIR" ]] || die "Graphify directory not found: $GRAPHIFY_DIR"
[[ -f "$GRAPHIFY_DIR/pyproject.toml" ]] || die "Graphify submodule appears uninitialized. Run: git submodule update --init graphify"

info "Graphify source: $GRAPHIFY_DIR"
info "Pinned commit:   $(cd "$GRAPHIFY_DIR" && git describe --tags --always 2>/dev/null)"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] uv pip install -e $GRAPHIFY_DIR"
  exit 0
fi

# Install via langywrap's 'knowledge-graph' optional-extra so subsequent
# `uv sync` calls keep textify+graphify in the lockfile. The
# [tool.uv.sources] block in pyproject.toml points graphifyy at the local
# submodule path (editable).
(cd "$LANGYWRAP_ROOT" && uv sync --extra knowledge-graph) || die "uv sync --extra knowledge-graph failed"

if (cd "$LANGYWRAP_ROOT" && uv run --no-sync graphify --help &>/dev/null); then
  ok "graphify installed in langywrap venv — run via: ./uv run graphify <cmd>"
else
  warn "graphify installed but CLI verification failed"
fi
