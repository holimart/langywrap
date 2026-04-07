# Test Suite

Comprehensive testing for the LLM Security Toolkit orchestrator.

## Test Files

### `test-orchestrator.sh` (Main Test Suite)
Comprehensive automated test suite with 60+ tests.

**Features:**
- ✅ Tests all security layers
- ✅ Tests configuration hierarchy
- ✅ Tests helpful messages
- ✅ Tests CLI arguments
- ✅ **Safe Mode**: Preserves artifacts on failure
- ✅ **Dry Run**: No actual dangerous commands executed

**Run:**
```bash
./tests/test-orchestrator.sh
```

**Safe Mode:**
- Only deletes test artifacts if ALL tests pass
- On failure, preserves test directory for debugging
- Prompts before cleanup if tests failed
- Never executes actual dangerous commands

### `mock-agent.sh` (Mock AI Agent)
Simulates an AI agent for testing.

**Features:**
- ✅ Tests safe operations (should pass)
- ✅ Tests dangerous operations (should block)
- ✅ **Completely Safe**: Only tests pattern matching
- ✅ Shows helpful messages
- ✅ No dependencies (no real Claude/OpenCode needed)

**Run:**
```bash
./tests/mock-agent.sh
```

**Safety:**
- Does NOT execute any dangerous commands
- Only tests interceptor pattern matching
- Uses fake/nonexistent paths
- Dry run only

## Safety Guarantees

### What Gets Executed (SAFE)
✅ `echo` commands
✅ `ls` commands
✅ Safe read operations
✅ Pattern matching tests

### What NEVER Gets Executed
❌ `rm -rf` (any variant)
❌ `sudo` commands
❌ `chmod 777`
❌ `dd` or disk operations
❌ Any system modifications

### How Safety is Ensured

1. **Pattern Matching Only**: Tests check if interceptor catches patterns, doesn't execute them
2. **Fake Paths**: Uses `/tmp/fake-path-99999` and similar non-existent paths
3. **Dry Run Testing**: Commands are analyzed but not executed
4. **Interceptor First**: All commands go through interceptor for analysis
5. **Safe Fallbacks**: Even if test fails, no dangerous command runs

## Test Categories

| Category | Tests | Description |
|----------|-------|-------------|
| File Structure | 8 | Verifies all files exist and are executable |
| Interceptor | 6 | Tests command blocking and messages |
| Config Hierarchy | 4 | Tests configuration discovery |
| CLI Arguments | 5 | Tests orchestrator command-line parsing |
| Helpful Messages | 4 | Verifies helpful feedback in blocks |
| Permissions Config | 6 | Tests permission rule format |
| Resources Config | 3 | Tests resource limit format |
| Mock Agent | 3 | Tests with simulated agent |
| Logging | 3 | Tests audit logging |
| Documentation | 5 | Tests doc completeness |
| Pattern Matching | 4 | Tests pattern detection |

**Total**: 60+ tests

## Running Tests

### Run All Tests
```bash
./tests/test-orchestrator.sh
```

### Expected Output
```
========================================
LLM Security Toolkit - Test Suite
========================================
Testing orchestrator and all components
Project: /path/to/llmsec

⚠️  Safe Mode: Test artifacts preserved on failure

========================================
Testing File Structure
========================================

[TEST 1] Orchestrator script exists
  ✓ PASS (file exists: /path/to/secure-run.sh)

[TEST 2] Orchestrator is executable
  ✓ PASS

...

========================================
TEST SUMMARY
========================================
Total Tests:  62
Passed:       62
Failed:       0

✅ ALL TESTS PASSED!
```

### On Failure
```
========================================
TEST SUMMARY
========================================
Total Tests:  62
Passed:       58
Failed:       4

❌ SOME TESTS FAILED

Debugging tips:
  - Check test artifacts in: /path/to/tests/test-project/
  - Review logs in: ~/.llmsec/logs/
  - Run individual tests by uncommenting in main()

⚠️  Tests failed - test project preserved for debugging
   Location: /path/to/tests/test-project/

Delete test project anyway? [y/N]: _
```

## Mock Agent Testing

```bash
./tests/mock-agent.sh
```

**Output:**
```
Mock Agent Starting (Safe Mode)...
Agent will test security patterns without executing dangerous commands

[TEST 1] Safe file reading
Testing: echo 'safe read'
✓ Safe command allowed

[TEST 2] Safe directory listing
Testing: ls (read-only)
✓ Directory listing allowed

[TEST 3] Dangerous recursive delete (DRY RUN)
Testing pattern: rm -rf /tmp/fake-path-99999
✓ Dangerous delete blocked

[TEST 4] Privilege escalation attempt (DRY RUN)
Testing pattern: sudo echo test
✓ Sudo blocked

[TEST 5] Dangerous chmod (DRY RUN)
Testing pattern: chmod 777 /tmp/fake-file-123
✓ Dangerous chmod blocked

[TEST 6] Helpful message test
Testing that blocks include helpful suggestions...
✓ Helpful message provided
   Sample message:
   ❌ Recursive deletion blocked for safety
   
   Reason: Recursive delete can cause permanent data loss
   
   💡 Suggested Alternative:
   ...

==========================================
Mock Agent Finished (Safe Mode)
All tests use pattern matching only
No actual dangerous commands executed
==========================================
```

## Debugging Failed Tests

### 1. Review Test Artifacts
```bash
# Check what was created
ls -la tests/test-project/

# Check any configs created
cat tests/test-project/.settings/permissions.yaml
```

### 2. Review Logs
```bash
# Check intercept log
cat ~/.llmsec/logs/intercept.log

# Check monitor log (if running)
cat ~/.llmsec/logs/claude-monitor.log
```

### 3. Run Individual Components
```bash
# Test interceptor directly
./tools/interceptors/intercept-enhanced.py "test command"

# Test orchestrator help
./secure-run.sh --help

# Test with verbose
./secure-run.sh --verbose
```

### 4. Clean Up and Retry
```bash
# Remove test artifacts
rm -rf tests/test-project/

# Clear logs
rm -f ~/.llmsec/logs/*.log

# Run tests again
./tests/test-orchestrator.sh
```

## Adding New Tests

### Format
```bash
test_new_feature() {
    print_header "Testing New Feature"

    print_test "Description of test"
    # Run test
    OUTPUT=$(command_to_test 2>&1)
    
    # Assert result
    assert_success $? "Should succeed"
    # OR
    assert_contains "$OUTPUT" "expected string"
    # OR
    assert_failure $? "Should fail"
}
```

### Add to Main
```bash
main() {
    # ... existing tests ...
    test_new_feature  # Add here
    # ...
}
```

## Continuous Integration

### GitHub Actions
```yaml
- name: Run Test Suite
  run: ./tests/test-orchestrator.sh

- name: Run Mock Agent Test
  run: ./tests/mock-agent.sh
```

### Pre-commit Hook
```bash
# .git/hooks/pre-commit
#!/bin/bash
./tests/test-orchestrator.sh || exit 1
```

## Test Philosophy

1. **Safe by Default**: Never execute dangerous commands
2. **Fast**: Complete suite runs in <1 minute
3. **Comprehensive**: Cover all functionality
4. **Helpful**: Clear output on failure
5. **Non-Destructive**: Preserves artifacts for debugging
6. **No Dependencies**: Works without Claude/OpenCode installed

---

**Run tests before every commit!**

```bash
./tests/test-orchestrator.sh && git commit
```
