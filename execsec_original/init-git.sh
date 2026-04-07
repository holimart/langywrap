#!/bin/bash
# Initialize Git repository and create initial commit

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================"
echo "Git Repository Initialization"
echo "======================================"
echo ""

# Check if already a git repo
if [ -d ".git" ]; then
    echo "⚠️  Git repository already exists."
    read -p "Reinitialize? This will preserve history. [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

# Initialize git
echo "Initializing Git repository..."
git init

# Configure git (optional)
echo ""
read -p "Configure git user? [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter your name: " GIT_NAME
    read -p "Enter your email: " GIT_EMAIL
    git config user.name "$GIT_NAME"
    git config user.email "$GIT_EMAIL"
    echo "✅ Git user configured"
fi

# Add all files
echo ""
echo "Adding files to git..."
git add .

# Create initial commit
echo "Creating initial commit..."
git commit -m "Initial commit: LLM Security Toolkit v0.1.0

- Complete project structure
- Phase 1 implementation (quick wins)
- Core security tools (intercept.py, monitor.sh)
- Comprehensive documentation
- Docker sandbox configuration
- Semgrep security rules
- Test suite
- MIT License

Includes research from 40+ sources covering:
- AI agent security best practices
- Tool interception and guardrails
- Execution isolation
- Static analysis and validation
- Monitoring and response

Ready for Phase 1 deployment.
"

echo ""
echo "======================================"
echo "✅ Git Repository Initialized"
echo "======================================"
echo ""
echo "Repository status:"
git log --oneline
echo ""
git status
echo ""
echo "Next steps:"
echo "  1. Create remote repository (GitHub, GitLab, etc.)"
echo "  2. Add remote: git remote add origin <url>"
echo "  3. Push: git push -u origin main"
echo ""
