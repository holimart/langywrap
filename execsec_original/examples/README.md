# Examples Directory

This directory contains example configurations, alternative setups, and legacy scripts.

## Contents

### `/alternative-setups/`
Alternative ways to set up security layers if you don't want to use the main orchestrator.

### `/legacy/`
Old installation scripts from before the orchestrator existed. Kept for reference.

- `manual-setup.sh` - Manual installation of security components
- `wizard-installer.sh` - Interactive installation wizard

## Recommended Approach

**Use the main orchestrator instead:**

```bash
cd /path/to/llmsec
./secure-run.sh
```

The orchestrator automatically handles all security layers with zero configuration needed.

## When to Use These Examples

- **Learning**: Understand how individual components work
- **Custom Setup**: Need a non-standard configuration
- **Integration**: Integrating security into existing systems
- **Debugging**: Troubleshooting individual layers

## Custom Configuration Examples

Coming soon:
- Project-specific permission examples
- Industry-specific security configs (healthcare, finance, etc.)
- Integration examples (CI/CD, IDE, etc.)
