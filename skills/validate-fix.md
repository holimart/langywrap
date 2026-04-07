---
description: Run all checks, fix errors, analyze code patterns, propose tests, and verify documentation
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(just), Task(Explore)
---

# Validate, Fix, and Review Workflow

Comprehensive workflow to run all code quality checks, fix issues, analyze code patterns for improvement opportunities, propose test improvements, and verify documentation is up-to-date with recent changes.

## Overview

This workflow:
1. Runs all linting, type checking, and tests
2. Auto-fixes what can be fixed
3. Manually fixes remaining errors
4. **Analyzes code patterns for refactoring opportunities**
5. Analyzes test coverage and proposes new tests
6. Reviews recent commits and ensures documentation reflects changes

## Step 1: Initial Assessment

First, understand what commands are available:

```bash
./just --list
```

Run the fix command to auto-fix style issues first:

```bash
./just fix 2>&1 | cat
```

## Step 2: Run Full Validation

Run the complete check suite:

```bash
./just check 2>&1 | cat
```

This runs: lint → typecheck → tests

If all passes, skip to Step 5. Otherwise proceed to Step 3.

## Step 3: Fix Errors

### Linting Errors

If lint errors remain after auto-fix, read the offending files and fix them:
- Import order issues
- Unused imports/variables
- Line length
- Code style violations

### Type Errors

For each type error:
1. Read the file at the specified line
2. Understand the type mismatch
3. Fix with proper type annotations or code changes
4. Common fixes:
   - Add `| None` for optional values
   - Use `cast()` for known-safe type narrowing
   - Add missing return type annotations
   - Fix incompatible argument types

### Test Failures

For each failing test:
1. Read the test file to understand what's being tested
2. Read the implementation being tested
3. Determine if the test or implementation is wrong
4. Fix the appropriate file

After fixing, re-run validation:

```bash
./just check 2>&1 | cat
```

Repeat until all checks pass.

## Step 4: Code Pattern Analysis (Optional)

Analyze the codebase for common patterns that could be abstracted or improved.

**Reference**: See `DESIGN_PRINCIPLES.md` for existing utilities and acceptance criteria.

### Pattern Detection Strategy

Use grep/ripgrep to find patterns. The search strategy:

1. **Search for repeated code** - Use grep with count to find duplicated patterns
2. **Count occurrences** - Quantify how widespread each pattern is
3. **Check DESIGN_PRINCIPLES.md** - See if a utility already exists for this pattern
4. **Prioritize by impact** - Focus on patterns exceeding thresholds (5+ Python, 3+ SQL)

### 4.1 Generic Pattern Search

Search for ANY repeated code patterns:

```bash
# Find repeated patterns (adjust regex as needed)
# Example: Similar function signatures
grep -rn "def extract_" . --include="*.py" | wc -l

# Example: Similar class patterns
grep -rn "class.*Loader" . --include="*.py" | wc -l

# Example: Repeated imports
grep -rn "^from datetime import" . --include="*.py" | wc -l

# Example: Similar error handling
grep -rn "except.*as e:" . --include="*.py" | head -20
```

### 4.2 Check Against Existing Utilities

Before proposing new abstractions, check what's already documented:

```bash
# Check utils module
ls -la [your-package]/utils/

# Check what's exported
grep -n "^def\|^class" [your-package]/utils/*.py
```

### 4.3 Identify Violations of Existing Acceptance Criteria

Check if code violates the acceptance criteria in `DESIGN_PRINCIPLES.md`:

```bash
# Example violations to search for
grep -rn "[your-specific-pattern]" . --include="*.py" | grep -v utils
```

### 4.4 Pattern Analysis Report

For each pattern category found, create a report:

```markdown
## Code Pattern Analysis

### Violations of Existing Acceptance Criteria

| Criterion | File:Line | Pattern Found | Should Use |
|-----------|-----------|---------------|------------|
| 1.1 | file.py:45 | `bad_pattern()` | `good_pattern()` |
| 2.3 | query.py:120 | `manual_division` | `safe_divide()` |

### New Patterns Discovered (candidates for new utilities)

| Pattern | Count | Example Location | Proposed Utility |
|---------|-------|------------------|------------------|
| `for k, v in dict.items()` | 8 | loader.py:200 | `filter_none_values()` |
| `try: int(x) except: None` | 6 | parser.py:50 | `sanitize_int()` |

### Recommendations

1. **Refactor existing code** to use utilities per acceptance criteria
2. **Add new utility** for pattern X (appears 7 times, >5 threshold)
3. **Update DESIGN_PRINCIPLES.md** with new acceptance criteria
```

### 4.5 Update Acceptance Criteria

**IMPORTANT**: When a new pattern is discovered and a utility is created:

1. Add the utility to `[your-package]/utils/`
2. Update `DESIGN_PRINCIPLES.md` with new acceptance criteria
3. The acceptance criteria format is (EARS):
   ```
   WHEN [condition] THE SYSTEM SHALL use [utility] instead of [anti-pattern]
   ```

### 4.6 When to Create New Utilities

Only propose new utilities when:
1. Pattern appears **5+ times** (Python) or **3+ times** (SQL) across different files
2. Pattern is **complex enough** (>3 lines) to warrant abstraction
3. **No existing utility** in `DESIGN_PRINCIPLES.md` covers the use case
4. Abstraction would **improve readability**, not just reduce lines

## Step 5: Test Coverage Analysis (Optional)

**Skip this step if using `quick` argument.**

Run tests with coverage report:

```bash
./uv run pytest --cov=[your-package] --cov-report=term-missing 2>&1 | cat
```

Analyze the output to identify:
1. **Uncovered files**: Files with 0% or very low coverage
2. **Uncovered lines**: Specific line ranges not exercised
3. **Missing edge cases**: Based on code patterns

### Proposing New Tests

For each uncovered area, propose a test:

```markdown
## Proposed Tests for Coverage

| File | Current Coverage | Proposed Test | Description |
|------|------------------|---------------|-------------|
| [package]/module.py | 45% | test_error_handling | Test error scenarios |
| [package]/component.py | 60% | test_edge_cases | Test with edge case data |
```

Focus on:
- Error handling paths (try/except blocks)
- Edge cases (empty data, None values, invalid inputs)
- Conditional branches not covered
- Integration points

## Step 6: Documentation Consistency Check (Optional)

**Skip this step if using `quick` argument.**

Use grep to perform systematic consistency checks between code and documentation.

### 6.1 Key Components Documentation Consistency

Check that all main components in code are documented:

```bash
# List main components in code
grep -rn "^class\|^def" [your-package]/ --include="*.py" | wc -l

# Check documentation mentions
grep -c "[component-name]" CLAUDE.md
```

### 6.2 Justfile-Documentation Consistency

Check that justfile commands are documented:

```bash
# Count justfile recipes
grep -c "^[a-z].*:" justfile

# List undocumented commands
for cmd in $(grep "^[a-z].*:" justfile | awk -F: '{print $1}'); do
  grep -q "$cmd" CLAUDE.md || echo "Missing: $cmd"
done
```

### 6.3 Skills-CLAUDE.md Consistency

Check that all skills are documented:

```bash
# List skill files
ls .claude/commands/*.md | wc -l

# Count skills in CLAUDE.md table
grep -c "^| \`/" CLAUDE.md
```

### 6.4 Generate Consistency Report

```markdown
## Documentation Consistency Report

### Key Components
| Status | Item | Issue |
|--------|------|-------|
| ❌ | NewComponent | Not in CLAUDE.md |
| ✅ | ExistingComponent | Documented |

### Justfile Commands
| Status | Command | Issue |
|--------|---------|-------|
| ❌ | new-command | Not documented in CLAUDE.md |
| ✅ | existing-command | Documented |

### Skills
| Status | Skill | Issue |
|--------|-------|-------|
| ❌ | /new-skill | File exists but not in CLAUDE.md |
| ✅ | /existing-skill | Consistent |

### Recommendations
1. Add missing components to CLAUDE.md
2. Document new justfile commands
3. Update skill descriptions
```

## Step 7: Review Recent Commits and Documentation (Optional)

**Skip this step if using `quick` arguments.**

### Get Recent Changes

```bash
git log --oneline -20 2>&1 | cat
```

```bash
git diff HEAD~5..HEAD --name-only 2>&1 | cat
```

### Identify Changed Areas

Group the changed files by area:
- `[package]/` - Core code changes
- `tests/` - Test changes
- `scripts/` - Script changes
- Documentation files

### Check Documentation Updates Needed

For each changed area, read the corresponding documentation:

| Changed Area | Documentation to Check |
|--------------|------------------------|
| Core code | `CLAUDE.md` (relevant sections), `README.md` |
| New scripts | `CLAUDE.md` (Development Commands), `justfile` |
| New tests | Ensure test describes the functionality being tested |
| Config changes | `.env`, `pyproject.toml`, `CLAUDE.md` (Configuration section) |

### Check Justfile Updates

If changes involve new commands or workflows, verify `justfile` has appropriate recipes:
- Run `./just --list` to see current commands
- Ensure new tools/scripts have corresponding justfile entries

### Verify Documentation Accuracy

For each documentation file:
1. Read the file
2. Compare against the code changes
3. Check if:
   - New features are documented
   - Changed behavior is reflected
   - Removed features are cleaned up
   - Examples are still accurate

### Generate Documentation Update Report

```markdown
## Documentation Review

### Files Needing Updates

| File | Section | Issue | Suggested Fix |
|------|---------|-------|---------------|
| CLAUDE.md | [Section] | [Issue] | [Fix] |
| README.md | [Section] | [Issue] | [Fix] |

### Files Already Up-to-Date
- [File1]
- [File2]
```

## Step 8: Final Report

Produce a summary:

```markdown
## Validation Summary

### Checks
- Lint: PASSED/FAILED (X errors fixed)
- Type check: PASSED/FAILED (X errors fixed)
- Tests: PASSED/FAILED (X/Y tests passing)

### Code Patterns
- Acceptance criteria violations: X
- New patterns discovered: Y candidates
- DESIGN_PRINCIPLES.md updates needed: YES/NO

### Documentation Consistency
- Files reviewed: X
- Updates needed: X
- Justfile commands: X total, Y documented

### Test Coverage
- Current: XX%
- Proposed tests: X new tests to add

### Documentation
- Files reviewed: X
- Updates needed: X
- All documentation current: YES/NO

### Action Items
1. [ ] Fix remaining lint errors in X files
2. [ ] Refactor code violating acceptance criteria
3. [ ] Add new utility for pattern X (if threshold met)
4. [ ] Update DESIGN_PRINCIPLES.md with new criteria
5. [ ] Document undocumented components
6. [ ] Update examples and README
7. [ ] Add tests for Y module
```

## Quick Reference Commands

```bash
# Fix code style
./just fix 2>&1 | cat

# Full check
./just check 2>&1 | cat

# Lint only
./just lint 2>&1 | cat

# Type check only
./just typecheck 2>&1 | cat

# Tests only
./just test 2>&1 | cat

# Tests verbose
./just testv 2>&1 | cat

# Specific test file
./just test-file tests/test_foo.py 2>&1 | cat

# Coverage report
./uv run pytest --cov=[your-package] --cov-report=term-missing 2>&1 | cat

# Recent commits
git log --oneline -10 2>&1 | cat

# Changed files
git diff HEAD~5..HEAD --name-only 2>&1 | cat

# Git status
git status 2>&1 | cat
```

## Arguments

$ARGUMENTS - Optional flags:
- `quick` - Skip coverage analysis, pattern analysis, and documentation review
- `patterns` - Run code pattern analysis (Step 4) as part of the workflow
- `patterns-only` - Only run code pattern analysis
- `coverage-only` - Only run coverage analysis
- `docs-only` - Only run documentation review (Step 7)
- `readme-check` - Only run documentation consistency check
- `fix-only` - Only run fix and validation (no proposals)
- `full` - Run all steps including pattern analysis and documentation check (default)

### Usage Examples

```bash
# Quick check: just fix + validate
/validate-fix quick

# Focus on code patterns
/validate-fix patterns-only

# Check documentation consistency only
/validate-fix readme-check

# Full validation including patterns (most thorough)
/validate-fix full

# Standard validation without patterns
/validate-fix
```
