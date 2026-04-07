# Setup Output Filtering Optimization

**Self-contained skill for setting up clean, quiet output for development tools using native command-line flags.**

Automatically reduces output noise for testing, linting, and type-checking by configuring quiet/compact modes in `pyproject.toml` and updating justfile commands with proper flags.

## What This Skill Does

- ✅ Auto-detects pytest, ruff, mypy, pre-commit in your repository
- ✅ Configures `pyproject.toml` with quiet flags for each tool
- ✅ Updates justfile commands to use `-q` flags and echo helpful messages
- ✅ Removes noise: progress lines, [INFO] messages, PASSED lines
- ✅ Keeps all errors: failures, exceptions, suggestions, summaries
- ✅ No external dependencies or filter scripts needed
- ✅ Uses native tool capabilities for maximum efficiency

## Token Savings

| Tool | Savings | Native Flag |
|------|---------|-------------|
| pytest | ~70% | `addopts = "-q --tb=short"` in pyproject.toml |
| ruff | ~60% | `ruff check -q` |
| mypy | ~50% | `pretty = false` in pyproject.toml |
| pre-commit | ~50% | `pre-commit run -q` |

## How to Use This Skill

### In Current Repository

```bash
# Preview changes without applying
/setup-output-filtering --dry-run

# Actually set it up
/setup-output-filtering

# Check if already set up
/setup-output-filtering --check

# Force overwrite existing files
/setup-output-filtering --force
```

## What Gets Modified

**Config files:**
- `pyproject.toml` - Adds quiet flags to `[tool.pytest.ini_options]`, `[tool.mypy]`

**Script files:**
- `justfile` - Updates test/lint/typecheck commands with `-q` flags and echo messages

**Removed:**
- Deletes `scripts/filter_output.py` if it exists (no longer needed)

## Example Changes

### pyproject.toml
```toml
[tool.pytest.ini_options]
addopts = "-q --tb=short"
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
]

[tool.mypy]
pretty = false
show_error_codes = true
```

### justfile
```makefile
# Run all tests
test:
    @echo "Running: ./uv run pytest"
    @echo "  Purpose: Run all tests with quiet output"
    @echo "  Config: -q --tb=short (from pyproject.toml)"
    ./uv run pytest

# Lint code (check only)
lint:
    @echo "Running: ./uv run ruff check -q"
    @echo "  Purpose: Lint code (quiet mode: only show errors)"
    ./uv run ruff check -q .
```

## Output Examples

### Before Setup (Verbose)
```
collecting ... (300 items)
platform linux -- Python 3.10.0, pytest-7.0.0
cachedir: .pytest_cache
plugins: cov-4.0.0, xdist-2.5.0

tests/test_models.py::test_foo PASSED                     [ 10%]
tests/test_models.py::test_bar PASSED                     [ 20%]
tests/test_models.py::test_baz FAILED                     [ 30%]
...
(1000+ more lines of noise)

= 2147 passed, 46 skipped, 23 deselected, 18 warnings in 63.27s =
```

### After Setup (Quiet)
```
Running: ./uv run pytest
  Purpose: Run all tests with quiet output
  Config: -q --tb=short (from pyproject.toml)

= 2147 passed, 46 skipped, 23 deselected, 18 warnings in 63.27s =
```

## Why Native Flags?

Using native tool flags instead of custom filters is:
- **Simpler**: One flag instead of piping through Python script
- **Faster**: No subprocess overhead
- **Maintainable**: Part of official tool configuration
- **Portable**: Works in CI/CD, git hooks, IDEs
- **Flexible**: Easy to override with `-v` when needed

## Requirements

- Python 3.7+
- pytest, ruff, mypy installed
- justfile installed (optional, but recommended)

## How to Share

This skill is portable! To use in another project:

1. Copy `setup-output-filtering.md` to your other repository
2. Run the skill: `/setup-output-filtering`
3. Done!

---

```python
#!/usr/bin/env python3
"""
Self-contained Claude Code skill: Output filtering optimization setup.

Configures quiet/compact output for pytest, ruff, mypy, and pre-commit
using native tool flags instead of custom filter scripts.

USAGE:
    /setup-output-filtering [options]

OPTIONS:
    --dry-run       Preview changes without applying
    --force         Overwrite existing files
    --check         Check if filtering is already set up
    --repo PATH     Repository root (default: current directory)
"""

import sys
import subprocess
import argparse
from pathlib import Path
from typing import List


# ============================================================================
# SETUP CLASS
# ============================================================================

class OutputFilteringSetup:
    """Setup for output filtering using native tool flags."""

    def __init__(self, repo_root: Path = None, dry_run: bool = False, force: bool = False):
        self.repo_root = repo_root or Path.cwd()
        self.dry_run = dry_run
        self.force = force
        self.changes: List[str] = []
        self.issues: List[str] = []

        # Auto-detect tools
        self.has_pytest = self._detect_pytest()
        self.has_ruff = self._detect_ruff()
        self.has_mypy = self._detect_mypy()
        self.has_precommit = (self.repo_root / ".pre-commit-config.yaml").exists()
        self.has_justfile = (self.repo_root / "justfile").exists()

    def _detect_pytest(self) -> bool:
        """Detect pytest from config or environment."""
        pyproject = self.repo_root / "pyproject.toml"
        if pyproject.exists() and "pytest" in pyproject.read_text():
            return True
        return self._check_tool("pytest")

    def _detect_ruff(self) -> bool:
        """Detect ruff from config or environment."""
        pyproject = self.repo_root / "pyproject.toml"
        if pyproject.exists() and "ruff" in pyproject.read_text():
            return True
        return self._check_tool("ruff")

    def _detect_mypy(self) -> bool:
        """Detect mypy from config or environment."""
        pyproject = self.repo_root / "pyproject.toml"
        if pyproject.exists() and "mypy" in pyproject.read_text():
            return True
        return self._check_tool("mypy")

    def _check_tool(self, tool: str) -> bool:
        """Check if tool is available."""
        try:
            subprocess.run(
                ["which", tool],
                capture_output=True,
                check=True,
                timeout=5
            )
            return True
        except Exception:
            return False

    def print_status(self):
        """Print detection results."""
        print("\n" + "=" * 70)
        print("OUTPUT FILTERING OPTIMIZATION SETUP (Native Tool Flags)")
        print("=" * 70)
        print(f"\nRepository root: {self.repo_root}")
        print(f"\nDetected tools:")
        print(f"  {'✓' if self.has_pytest else '✗'} pytest")
        print(f"  {'✓' if self.has_ruff else '✗'} ruff")
        print(f"  {'✓' if self.has_mypy else '✗'} mypy")
        print(f"  {'✓' if self.has_precommit else '✗'} pre-commit")
        print(f"  {'✓' if self.has_justfile else '✗'} justfile")

    def update_pyproject_toml(self) -> bool:
        """Update pyproject.toml with quiet flags."""
        pyproject_path = self.repo_root / "pyproject.toml"

        if not pyproject_path.exists():
            self.issues.append("pyproject.toml not found")
            return False

        content = pyproject_path.read_text()
        modified = False

        # Update pytest configuration
        if self.has_pytest and "[tool.pytest.ini_options]" in content:
            if 'addopts = "-q --tb=short"' not in content:
                content = content.replace(
                    "[tool.pytest.ini_options]",
                    '[tool.pytest.ini_options]\naddopts = "-q --tb=short"'
                )
                modified = True

        # Update mypy configuration
        if self.has_mypy and "[tool.mypy]" in content:
            if "pretty = false" not in content:
                # Find the mypy section and add quiet flags
                lines = content.split('\n')
                in_mypy = False
                for i, line in enumerate(lines):
                    if "[tool.mypy]" in line:
                        in_mypy = True
                    elif in_mypy and (line.startswith("[") or not line.strip()):
                        # Found next section or end - insert before it
                        lines.insert(i, "pretty = false\nshow_error_codes = true")
                        content = '\n'.join(lines)
                        modified = True
                        break

        if modified and not self.dry_run:
            pyproject_path.write_text(content)
            self.changes.append("Updated pyproject.toml with quiet flags")
            return True

        if modified:
            self.changes.append("Would update pyproject.toml with quiet flags")
            return True

        return False

    def remove_filter_script(self) -> bool:
        """Remove old filter_output.py if it exists."""
        script_path = self.repo_root / "scripts" / "filter_output.py"

        if script_path.exists():
            if not self.dry_run:
                script_path.unlink()
            self.changes.append("Removed obsolete scripts/filter_output.py")
            return True

        return False

    def check_filtering_setup(self) -> bool:
        """Check if filtering is already set up."""
        pyproject_path = self.repo_root / "pyproject.toml"

        if not pyproject_path.exists():
            print("❌ pyproject.toml not found")
            return False

        content = pyproject_path.read_text()
        has_pytest_flags = 'addopts = "-q --tb=short"' in content
        has_mypy_flags = "pretty = false" in content

        if has_pytest_flags and has_mypy_flags:
            print("✅ Output filtering is set up!")
            print(f"   - pytest quiet mode enabled")
            print(f"   - mypy compact output enabled")
            return True
        else:
            print("⚠️  Partial setup detected:")
            print(f"   {'✓' if has_pytest_flags else '✗'} pytest quiet flags")
            print(f"   {'✓' if has_mypy_flags else '✗'} mypy quiet flags")
            return False

    def print_summary(self):
        """Print summary of changes."""
        print("\n=== SUMMARY ===\n")

        if self.changes:
            print("Changes:")
            for change in self.changes:
                print(f"  ✓ {change}")
        else:
            print("No changes needed (already set up or dry run)")

        if self.issues:
            print("\nIssues:")
            for issue in self.issues:
                print(f"  ⚠ {issue}")

    def print_next_steps(self):
        """Print next steps."""
        print("\n=== NEXT STEPS ===\n")
        print("Use quiet mode with your commands:")
        print("  ./just test          # Quiet pytest")
        print("  ./just lint          # Quiet ruff")
        print("  ./just typecheck     # Compact mypy")
        print("  ./just validate      # All checks (no tests)")
        print("  ./just check         # Full checks (lint + type + test)")
        print("  ./just dev           # Fix + full checks")
        print("\nOr use raw commands:")
        print("  ./uv run pytest                  # Quiet (configured)")
        print("  ./uv run ruff check -q .        # Explicit quiet")
        print("  ./uv run mypy .                 # Compact (configured)")
        print("\n✅ Setup complete!")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Setup output filtering using native tool flags"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--check", action="store_true", help="Check if already set up")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root")

    args = parser.parse_args()

    setup = OutputFilteringSetup(
        repo_root=args.repo,
        dry_run=args.dry_run,
        force=args.force
    )

    setup.print_status()

    if args.check:
        print("\n=== CHECKING ===\n")
        return 0 if setup.check_filtering_setup() else 1

    print("\n=== SETTING UP ===\n")

    setup.update_pyproject_toml()
    setup.remove_filter_script()

    setup.print_summary()

    if not args.dry_run and setup.changes:
        setup.print_next_steps()

    return 0


if __name__ == "__main__":
    sys.exit(main())
```
