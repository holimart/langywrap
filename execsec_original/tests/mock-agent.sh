#!/bin/bash
# Mock AI Agent for Testing
# Simulates an AI agent that tries various commands
# SAFE MODE: Only tests pattern matching, doesn't execute dangerous commands

echo "Mock Agent Starting (Safe Mode)..."
echo "Agent will test security patterns without executing dangerous commands"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INTERCEPTOR="$PROJECT_ROOT/tools/interceptors/intercept-enhanced.py"

# Test safe operations (should pass)
echo "[TEST 1] Safe file reading"
echo "Testing: echo 'safe read'"
$INTERCEPTOR "echo 'safe read'" > /dev/null 2>&1 && echo "✓ Safe command allowed" || echo "✗ Safe command blocked"

echo ""
echo "[TEST 2] Safe directory listing"
echo "Testing: ls (read-only)"
$INTERCEPTOR "ls" > /dev/null 2>&1 && echo "✓ Directory listing allowed" || echo "✗ Directory listing blocked"

# Test dangerous operations (should block) - DRY RUN ONLY
echo ""
echo "[TEST 3] Dangerous recursive delete (DRY RUN)"
echo "Testing pattern: rm -rf /tmp/fake-path-99999"
OUTPUT=$($INTERCEPTOR "rm -rf /tmp/fake-path-99999" 2>&1 || true)
echo "$OUTPUT" | grep -q "blocked" && echo "✓ Dangerous delete blocked" || echo "✗ Dangerous delete NOT blocked"

echo ""
echo "[TEST 4] Privilege escalation attempt (DRY RUN)"
echo "Testing pattern: sudo echo test"
OUTPUT=$($INTERCEPTOR "sudo echo test" 2>&1 || true)
echo "$OUTPUT" | grep -q "blocked\|not permitted" && echo "✓ Sudo blocked" || echo "✗ Sudo NOT blocked"

echo ""
echo "[TEST 5] Dangerous chmod (DRY RUN)"
echo "Testing pattern: chmod 777 /tmp/fake-file-123"
OUTPUT=$($INTERCEPTOR "chmod 777 /tmp/fake-file-123" 2>&1 || true)
echo "$OUTPUT" | grep -q "blocked\|permissions" && echo "✓ Dangerous chmod blocked" || echo "✗ Dangerous chmod NOT blocked"

echo ""
echo "[TEST 6] Helpful message test"
echo "Testing that blocks include helpful suggestions..."
OUTPUT=$($INTERCEPTOR "rm -rf /tmp/test" 2>&1 || true)
if echo "$OUTPUT" | grep -q "Alternative\|suggestion"; then
    echo "✓ Helpful message provided"
    echo "   Sample message:"
    echo "$OUTPUT" | head -10 | sed 's/^/   /'
else
    echo "✗ No helpful message found"
fi

echo ""
echo "=========================================="
echo "Mock Agent Finished (Safe Mode)"
echo "All tests use pattern matching only"
echo "No actual dangerous commands executed"
echo "=========================================="
exit 0
