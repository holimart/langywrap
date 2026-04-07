#!/bin/bash
# Phase 1: Quick Wins Setup Script
# Estimated time: 30 minutes
# Cost: $0
# Impact: HIGH

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_DIR="$HOME/bin"

echo "======================================"
echo "LLM Security Toolkit - Phase 1 Setup"
echo "======================================"
echo ""
echo "This will install basic security protections:"
echo "  ✓ Emergency kill switch"
echo "  ✓ Resource limits"
echo "  ✓ Claude Code permission settings"
echo ""
read -p "Continue? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Setup cancelled."
    exit 0
fi

# Create bin directory if it doesn't exist
echo "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# 1. Emergency Kill Script
echo ""
echo "[1/4] Installing emergency kill switch..."
cat > "$INSTALL_DIR/kill-claude.sh" << 'EOF'
#!/bin/bash
# Emergency stop for Claude Code and all child processes

echo "🛑 EMERGENCY STOP - Killing Claude Code and children..."

pkill -f "claude" 2>/dev/null
pkill -f "node.*claude" 2>/dev/null
pkill -f "npm" 2>/dev/null
pkill -f "yarn" 2>/dev/null
pkill -f "python.*$(pwd)" 2>/dev/null

echo "✅ Done. Check with: ps aux | grep -E 'claude|node|npm|python'"
EOF
chmod +x "$INSTALL_DIR/kill-claude.sh"
echo "   ✓ Installed: $INSTALL_DIR/kill-claude.sh"

# 2. Resource Limits Alias
echo ""
echo "[2/4] Setting up resource limits..."
SHELL_RC=""
if [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
fi

if [ -n "$SHELL_RC" ]; then
    if ! grep -q "claude-safe" "$SHELL_RC"; then
        cat >> "$SHELL_RC" << 'EOF'

# LLM Security Toolkit - Resource Limits
alias claude-safe='ulimit -v 4000000 -t 300 -f 1000000 && claude'
# -v 4GB max virtual memory
# -t 300 second CPU time limit
# -f 1GB max file size
EOF
        echo "   ✓ Added 'claude-safe' alias to $SHELL_RC"
    else
        echo "   ✓ Resource limits already configured"
    fi
else
    echo "   ⚠ Could not find shell RC file. Add manually to your shell config."
fi

# 3. Claude Settings
echo ""
echo "[3/4] Configuring Claude Code permissions..."
CLAUDE_DIR="$HOME/.claude"
mkdir -p "$CLAUDE_DIR"

if [ -f "$CLAUDE_DIR/settings.json" ]; then
    echo "   ⚠ $CLAUDE_DIR/settings.json already exists"
    read -p "   Overwrite with security settings? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp "$PROJECT_ROOT/configs/claude/settings.json" "$CLAUDE_DIR/settings.json"
        echo "   ✓ Settings updated"
    else
        echo "   ℹ Skipped. Merge manually from: $PROJECT_ROOT/configs/claude/settings.json"
    fi
else
    cp "$PROJECT_ROOT/configs/claude/settings.json" "$CLAUDE_DIR/settings.json"
    echo "   ✓ Settings installed"
fi

# 4. Enable Claude Sandbox
echo ""
echo "[4/4] Claude Code sandbox configuration..."
echo "   ℹ To enable Claude's built-in sandbox, run:"
echo "     /sandbox"
echo "   Then select: 'Sandbox with network restrictions'"
echo ""

# Summary
echo ""
echo "======================================"
echo "✅ Phase 1 Setup Complete!"
echo "======================================"
echo ""
echo "Installed components:"
echo "  • Emergency kill switch: $INSTALL_DIR/kill-claude.sh"
echo "  • Resource limits: 'claude-safe' command"
echo "  • Claude permissions: $CLAUDE_DIR/settings.json"
echo ""
echo "Next steps:"
echo "  1. Reload your shell: source $SHELL_RC"
echo "  2. Test kill switch: $INSTALL_DIR/kill-claude.sh"
echo "  3. Enable Claude sandbox: Run /sandbox in Claude Code"
echo ""
echo "For more security layers, run:"
echo "  • Phase 2 (Tool Interception): ./scripts/phase2/setup.sh"
echo "  • Phase 3 (Isolation): ./scripts/phase3/setup.sh"
echo ""
