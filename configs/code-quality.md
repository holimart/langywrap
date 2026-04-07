# Code Quality & Configuration Guide

This document explains the code quality configuration and how to prevent conflicts between development workflows.

## Configuration Details

### Mypy Configuration (`pyproject.toml`)
```toml
[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
ignore_missing_imports = true  # Handles third-party packages without type stubs
exclude = ["scripts/", "tests/"]  # Exclude exploratory/test code from strict checks
```

### Justfile Typecheck Command
```justfile
# Type check
typecheck:
    ./uv run mypy --config-file=pyproject.toml .
```

## Preventing Future Issues

### For New Third-Party Dependencies
1. **Check for type stubs**: Run `./just dev` after adding new dependencies
2. **Automatic handling**: The `ignore_missing_imports = true` setting handles packages without stubs
3. **For strict typing**: Consider adding type stubs or creating `.pyi` files

### Development Workflow
1. **Use `./just dev`**: Ensures consistent checking across environments
2. **Run pre-commit**: `./uv run pre-commit run --all-files` before committing
3. **Verify both pass**: Ensure both workflows use the same configuration

### Best Practices
- **Document type ignore comments**: Add brief explanations when using `# type: ignore`
- **Prefer configuration**: Use `pyproject.toml` settings over inline comments when possible
- **Test both workflows**: Always verify `./just dev` and pre-commit pass

## Checklist for Adding Dependencies
- [ ] Add dependency with `./uv add package-name`
- [ ] Run `./just dev` to check for type issues
- [ ] Verify pre-commit passes: `./uv run pre-commit run --all-files`
- [ ] Document any special type handling requirements

## Troubleshooting

### If mypy errors occur:
1. **Check the error type**: Is it about missing imports or actual type issues?
2. **For import errors**: The configuration should handle them automatically
3. **For type errors**: Fix the type annotations in your code
4. **If conflicts persist**: Ensure both `./just dev` and pre-commit use `--config-file=pyproject.toml`

### If pre-commit fails but just dev passes:
1. **Check configuration**: Both should use the same mypy settings
2. **Run verbose**: `./uv run pre-commit run --all-files --verbose` for details
3. **Compare environments**: Ensure same Python/mypy versions

### Common Line Length Issues (E501)
When lines exceed the configured limit (default 100 chars):
- Split long strings using concatenation
- Break function calls across multiple lines
- Use intermediate variables for complex expressions

## Key Configuration Files
- `pyproject.toml` - Mypy, ruff, pytest configuration
- `justfile` - Development commands
- `.pre-commit-config.yaml` - Pre-commit hook configuration (if used)

This configuration prevents conflicts while maintaining strict type checking for your code.
