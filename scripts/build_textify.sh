#!/usr/bin/env bash
# =============================================================================
# Install textify from the vendored submodule (editable)
# =============================================================================
# Installs the textify submodule into langywrap's uv environment as an
# editable dependency with the [full] extra (pypdf, python-docx, openpyxl,
# pymupdf, pdf2image, pytesseract, beautifulsoup4). Textify is LLM-free —
# deterministic PDF/DOCX/XLSX/HTML/image text extraction.
#
# Usage: ./scripts/build_textify.sh [--dry-run]
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
TEXTIFY_DIR="$LANGYWRAP_ROOT/textify"

echo -e "${BOLD}${CYAN}Installing Textify (editable, from submodule)${NC}"

command -v uv &>/dev/null || die "uv not found — install from https://docs.astral.sh/uv/"

[[ -d "$TEXTIFY_DIR" ]] || die "Textify directory not found: $TEXTIFY_DIR"
[[ -f "$TEXTIFY_DIR/pyproject.toml" ]] || die "Textify submodule appears uninitialized. Run: git submodule update --init textify"

info "Textify source: $TEXTIFY_DIR"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] uv pip install -e $TEXTIFY_DIR[full]"
  exit 0
fi

# Install via langywrap's own 'knowledge-graph' optional-extra so that
# subsequent `uv sync` calls keep textify+graphify in the lock. This pulls
# both tools (textify and graphifyy) — they are peers in the same extra,
# and both scripts are idempotent. The [tool.uv.sources] block in
# pyproject.toml points these packages at the local submodule paths.
(cd "$LANGYWRAP_ROOT" && uv sync --extra knowledge-graph) || die "uv sync --extra knowledge-graph failed"

if (cd "$LANGYWRAP_ROOT" && uv run --no-sync textify --help &>/dev/null); then
  ok "textify installed in langywrap venv — run via: ./uv run textify <src> <dst>"
else
  warn "textify installed but CLI verification failed"
fi
