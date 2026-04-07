#!/bin/bash
# LLM Security Toolkit - Main Installer
# This is the master installation script that guides users through setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}======================================"
    echo -e "$1"
    echo -e "======================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

clear
print_header "LLM Security Toolkit Installer"
echo ""
echo "This installer will help you set up security layers for AI agents."
echo ""
echo "Available security levels:"
echo ""
echo "  1. Basic (30 min)        - Essential protection, blocks destructive commands"
echo "  2. Recommended (2-3 hrs) - Basic + command interception + containers"
echo "  3. Maximum (4-8 hrs)     - All layers including microVM isolation"
echo "  4. Custom               - Choose individual phases"
echo ""

read -p "Select security level [1-4]: " LEVEL

case $LEVEL in
    1)
        print_header "Installing Basic Security (Level 1)"
        echo ""
        print_info "This will install Phase 1 components:"
        echo "  • Emergency kill switch"
        echo "  • Resource limits"
        echo "  • Claude Code permission rules"
        echo "  • Destructive command blocking"
        echo ""

        if [ -f "$SCRIPT_DIR/scripts/phase1/setup.sh" ]; then
            "$SCRIPT_DIR/scripts/phase1/setup.sh"
        else
            print_error "Phase 1 setup script not found!"
            exit 1
        fi
        ;;

    2)
        print_header "Installing Recommended Security (Level 2)"
        echo ""
        print_info "This will install Phases 1-2:"
        echo "  Phase 1: Basic protection (30 min)"
        echo "  Phase 2: Command interception (2 hrs)"
        echo ""

        # Phase 1
        if [ -f "$SCRIPT_DIR/scripts/phase1/setup.sh" ]; then
            "$SCRIPT_DIR/scripts/phase1/setup.sh"
        else
            print_error "Phase 1 setup script not found!"
            exit 1
        fi

        # Phase 2
        print_info "Phase 2 setup coming soon. Manual installation required."
        print_info "See: docs/guides/phase2-interception.md"
        ;;

    3)
        print_header "Installing Maximum Security (Level 3)"
        echo ""
        print_warning "This will install all 5 phases (4-8 hours total)"
        echo ""
        read -p "Continue? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Installation cancelled."
            exit 0
        fi

        print_info "Maximum security setup coming soon."
        print_info "For now, run phases individually:"
        echo "  ./scripts/phase1/setup.sh"
        echo "  ./scripts/phase2/setup.sh"
        echo "  ./scripts/phase3/setup.sh"
        echo "  ./scripts/phase4/setup.sh"
        echo "  ./scripts/phase5/setup.sh"
        ;;

    4)
        print_header "Custom Installation"
        echo ""
        echo "Select phases to install (space-separated, e.g., '1 2 4'):"
        echo "  1 - Quick Wins (30 min)"
        echo "  2 - Tool Interception (2 hrs)"
        echo "  3 - Execution Isolation (4-8 hrs)"
        echo "  4 - Output Validation (1 hr)"
        echo "  5 - Monitoring (1 hr)"
        echo ""
        read -p "Phases to install: " PHASES

        for PHASE in $PHASES; do
            case $PHASE in
                1)
                    if [ -f "$SCRIPT_DIR/scripts/phase1/setup.sh" ]; then
                        "$SCRIPT_DIR/scripts/phase1/setup.sh"
                    fi
                    ;;
                2|3|4|5)
                    print_warning "Phase $PHASE setup script not yet implemented"
                    print_info "See: docs/guides/phase${PHASE}-*.md"
                    ;;
                *)
                    print_error "Invalid phase: $PHASE"
                    ;;
            esac
        done
        ;;

    *)
        print_error "Invalid selection"
        exit 1
        ;;
esac

# Post-installation
echo ""
print_header "Installation Summary"
echo ""
print_success "Installation complete!"
echo ""
print_info "Next steps:"
echo "  1. Reload your shell:"
echo "     source ~/.bashrc  # or ~/.zshrc"
echo ""
echo "  2. Test the installation:"
echo "     $SCRIPT_DIR/tests/test-phase1.sh"
echo ""
echo "  3. Read the quick start guide:"
echo "     cat $SCRIPT_DIR/docs/QUICKSTART.md"
echo ""
echo "  4. Enable Claude sandbox mode:"
echo "     Run '/sandbox' in Claude Code"
echo ""

print_warning "Remember to review and customize configs/claude/settings.json"
echo ""
