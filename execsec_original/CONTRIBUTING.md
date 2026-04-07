# Contributing to LLM Security Toolkit

Thank you for your interest in contributing! This project aims to make AI agent security accessible and practical.

## How to Contribute

### Reporting Issues

- **Security vulnerabilities**: Please email security@[domain] instead of opening a public issue
- **Bugs**: Open an issue with detailed reproduction steps
- **Feature requests**: Open an issue describing the use case

### Code Contributions

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature`
3. **Make your changes**
4. **Test thoroughly**: Run `./tests/test-phase1.sh` (and other relevant tests)
5. **Commit with clear messages**: Follow conventional commits format
6. **Push and create a pull request**

### Adding New Security Tools

When adding a new security tool or script:

1. **Place in the appropriate directory**:
   - `/scripts/phaseX/` for installation scripts
   - `/tools/` for runtime utilities
   - `/configs/` for configuration templates

2. **Document thoroughly**:
   - Add comments explaining what it does
   - Include usage examples
   - Document dependencies

3. **Follow the security-first principle**:
   - Default to deny/block
   - Fail closed, not open
   - Log all security decisions

4. **Test on multiple platforms**:
   - Linux (Ubuntu/Debian, Fedora, Arch)
   - macOS
   - Document any platform-specific requirements

### Code Style

**Shell Scripts**:
- Use `#!/bin/bash` shebang
- Enable strict mode: `set -e`
- Use meaningful variable names in UPPERCASE for globals
- Add comments for complex logic
- Always quote variables: `"$VAR"` not `$VAR`

**Python Scripts**:
- Follow PEP 8
- Use type hints
- Include docstrings
- Python 3.8+ compatible

**Documentation**:
- Use clear, concise language
- Include examples
- Explain *why*, not just *what*

### Adding Documentation

- Detailed guides go in `/docs/guides/`
- Research and references go in `/docs/`
- Update README.md if adding major features
- Update QUICKSTART.md if changing installation

### Testing

Before submitting a PR:

```bash
# Run tests
./tests/test-phase1.sh

# Test on a fresh system if possible
# Use Docker to simulate clean environment
docker run -it ubuntu:22.04 bash
```

## Project Structure

```
llmsec/
├── scripts/       # Installation and setup scripts (organized by phase)
├── tools/         # Runtime utilities (monitors, interceptors, validators)
├── configs/       # Configuration templates
├── docs/          # Documentation
├── tests/         # Test suites
└── examples/      # Example implementations
```

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/llmsec.git
cd llmsec

# Create development branch
git checkout -b dev/your-feature

# Make scripts executable
find scripts tools -type f -name "*.sh" -exec chmod +x {} \;
find tools -type f -name "*.py" -exec chmod +x {} \;
```

## Commit Messages

Use conventional commits:

```
feat: add gVisor setup script for Phase 3
fix: correct permission check in intercept.py
docs: update QUICKSTART with Docker instructions
test: add integration tests for Phase 2
chore: update dependencies
```

## Security Considerations

When contributing security features:

1. **Assume adversarial input**: All external input is potentially malicious
2. **Defense in depth**: Multiple layers of protection
3. **Least privilege**: Grant minimum necessary permissions
4. **Fail secure**: If in doubt, block/deny
5. **Audit everything**: Log security decisions

### Example Security Checklist

- [ ] Does this properly validate input?
- [ ] Can this be bypassed with special characters?
- [ ] Does this log security-relevant events?
- [ ] Is the default configuration secure?
- [ ] Could this leak sensitive information?
- [ ] Does this handle errors securely?

## Adding Research References

When adding new research or tools:

1. Add to `docs/AI_AGENT_SECURITY_RESEARCH.md`
2. Include: Tool name, description, URL, use case
3. Categorize appropriately
4. Verify links are working

## Pull Request Process

1. **Update documentation** for any user-facing changes
2. **Add tests** if adding new functionality
3. **Update CHANGELOG.md** with your changes
4. **Request review** from maintainers
5. **Address feedback** promptly

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Security enhancement

## Testing
Describe testing performed

## Checklist
- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] Tests added/updated
- [ ] All tests pass
```

## Community

- Be respectful and professional
- Help others learn
- Share knowledge
- Credit others' work

## Questions?

Open a discussion on GitHub or reach out to maintainers.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
