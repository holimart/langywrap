#!/usr/bin/env bash
# =============================================================================
# Build OpenWolf from source and install
# =============================================================================
# Builds the OpenWolf submodule and links/copies the CLI to ~/.local/bin/openwolf.
#
# Usage: ./scripts/build_openwolf.sh [--dry-run]
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
OPENWOLF_DIR="$LANGYWRAP_ROOT/openwolf"
LOCAL_BIN="$HOME/.local/bin"

echo -e "${BOLD}${CYAN}Building OpenWolf${NC}"

# Check prerequisites
command -v node &>/dev/null || die "node not found — install Node.js >= 20"
NODE_MAJOR=$(node -v | sed 's/v//' | cut -d. -f1)
(( NODE_MAJOR >= 20 )) || die "Node.js >= 20 required (found v$NODE_MAJOR)"

command -v pnpm &>/dev/null || die "pnpm not found — install with: npm install -g pnpm"

# Check submodule
[[ -d "$OPENWOLF_DIR" ]] || die "OpenWolf directory not found: $OPENWOLF_DIR"
[[ -f "$OPENWOLF_DIR/package.json" ]] || die "OpenWolf submodule appears uninitialized. Run: git submodule update --init"

info "OpenWolf source: $OPENWOLF_DIR"
info "Destination: $LOCAL_BIN/openwolf"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] cd $OPENWOLF_DIR && pnpm install && pnpm build"
  echo "[dry-run] ln -sf $OPENWOLF_DIR/dist/bin/openwolf.js $LOCAL_BIN/openwolf"
  exit 0
fi

# Build
info "Running pnpm install..."
(cd "$OPENWOLF_DIR" && pnpm install) || die "pnpm install failed"

info "Running pnpm build..."
(cd "$OPENWOLF_DIR" && pnpm build) || die "pnpm build failed"

# Verify build output
[[ -f "$OPENWOLF_DIR/dist/bin/openwolf.js" ]] || die "Build succeeded but dist/bin/openwolf.js not found"

# Install to ~/.local/bin via wrapper script
mkdir -p "$LOCAL_BIN"
cat > "$LOCAL_BIN/openwolf" << WRAPPER
#!/usr/bin/env bash
exec node "$OPENWOLF_DIR/dist/bin/openwolf.js" "\$@"
WRAPPER
chmod +x "$LOCAL_BIN/openwolf"
ok "Installed → $LOCAL_BIN/openwolf"

# Verify
OW_VERSION=$("$LOCAL_BIN/openwolf" --version 2>&1 | head -1) || OW_VERSION="(could not determine)"
ok "OpenWolf version: $OW_VERSION"

# PATH reminder
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
  warn "$LOCAL_BIN not in PATH — add to your shell profile:"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
