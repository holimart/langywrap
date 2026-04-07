#!/usr/bin/env bash
# =============================================================================
# Build RTK from source and install
# =============================================================================
# Builds the RTK submodule and copies the binary to ~/.local/bin/rtk
# and langywrap's own .exec/rtk.
#
# Usage: ./scripts/build_rtk.sh [--dry-run]
# =============================================================================

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[ok]${NC}    $*"; }
info() { echo -e "${CYAN}[info]${NC}  $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANGYWRAP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RTK_DIR="$LANGYWRAP_ROOT/rtk"
LOCAL_BIN="$HOME/.local/bin"
EXEC_DIR="$LANGYWRAP_ROOT/.exec"
RTK_RELEASE="$RTK_DIR/target/release/rtk"

echo -e "${BOLD}${CYAN}Building RTK${NC}"

# Check cargo
command -v cargo &>/dev/null || die "cargo not found — install Rust from https://rustup.rs/"

# Check submodule
[[ -d "$RTK_DIR" ]] || die "RTK directory not found: $RTK_DIR"
[[ -f "$RTK_DIR/Cargo.toml" ]] || die "RTK submodule appears uninitialized. Run: git submodule update --init"

info "RTK source: $RTK_DIR"
info "Destination: $LOCAL_BIN/rtk"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] cd $RTK_DIR && cargo build --release"
  echo "[dry-run] cp $RTK_RELEASE $LOCAL_BIN/rtk"
  echo "[dry-run] cp $RTK_RELEASE $EXEC_DIR/rtk"
  exit 0
fi

# Build
info "Running cargo build --release..."
(cd "$RTK_DIR" && cargo build --release) || die "cargo build failed"

# Verify binary exists
[[ -f "$RTK_RELEASE" ]] || die "Build succeeded but binary not found at $RTK_RELEASE"

# Install to ~/.local/bin
mkdir -p "$LOCAL_BIN"
cp "$RTK_RELEASE" "$LOCAL_BIN/rtk"
chmod +x "$LOCAL_BIN/rtk"
ok "Installed → $LOCAL_BIN/rtk"

# Install to .exec/ for local use
mkdir -p "$EXEC_DIR"
cp "$RTK_RELEASE" "$EXEC_DIR/rtk"
chmod +x "$EXEC_DIR/rtk"
ok "Installed → $EXEC_DIR/rtk"

# Verify
RTK_VERSION=$(PATH="$LOCAL_BIN:$PATH" rtk --version 2>&1 | head -1) || RTK_VERSION="(could not determine)"
ok "RTK version: $RTK_VERSION"

# PATH reminder
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
  warn "$LOCAL_BIN not in PATH — add to your shell profile:"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
