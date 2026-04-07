#!/usr/bin/env python3
"""
Enhanced Command Interceptor with Helpful Messages
Part of LLM Security Toolkit

This interceptor reads configuration files and provides polite, constructive
feedback when blocking commands, suggesting safe alternatives.
"""

import sys
import re
import subprocess
import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ============================================================================
# CONFIGURATION LOADING
# ============================================================================

def find_config_file(filename: str, search_dirs: List[str]) -> Optional[str]:
    """Find config file in search directories"""
    for dir_path in search_dirs:
        file_path = Path(dir_path) / filename
        if file_path.exists():
            return str(file_path)
    return None

def load_permissions_config() -> Dict:
    """Load permissions configuration from hierarchy"""
    # Search directories (in order of preference)
    search_dirs = [
        os.getcwd() + "/.settings",
        os.getcwd() + "/.claude",
        os.getcwd() + "/.opencode",
        os.path.expanduser("~/.llmsec/defaults"),
        os.path.dirname(__file__) + "/../../configs/defaults",
    ]

    config_file = find_config_file("permissions.yaml", search_dirs)

    if config_file:
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)

    # Fallback to minimal default
    return {
        'deny': [],
        'ask': [],
        'allow': [],
    }

# ============================================================================
# COMMAND ANALYSIS
# ============================================================================

def parse_command(command: str) -> Tuple[str, List[str]]:
    """Parse command into program and arguments"""
    parts = command.split()
    if not parts:
        return "", []
    return parts[0], parts[1:]

def match_pattern(command: str, pattern: str) -> bool:
    """Check if command matches a pattern"""
    # Convert simple patterns to regex
    # Pattern format: "cmd:arg" or "cmd:*"

    if ':' in pattern:
        cmd_pattern, arg_pattern = pattern.split(':', 1)
    else:
        cmd_pattern = pattern
        arg_pattern = '*'

    cmd, args = parse_command(command)

    # Check command match
    if cmd_pattern != '*' and cmd != cmd_pattern:
        return False

    # Check args match
    if arg_pattern == '*':
        return True

    args_str = ' '.join(args)

    # Simple substring match or regex
    if arg_pattern.startswith('regex:'):
        regex = arg_pattern[6:]
        return bool(re.search(regex, args_str, re.IGNORECASE))
    else:
        return arg_pattern in args_str

def find_matching_rule(command: str, rules: List[Dict]) -> Optional[Dict]:
    """Find first rule that matches command"""
    for rule in rules:
        pattern = rule.get('pattern', '')
        if match_pattern(command, pattern):
            return rule
    return None

# ============================================================================
# MESSAGE FORMATTING
# ============================================================================

def format_message(template: str, context: Dict) -> str:
    """Format message template with context"""
    try:
        return template.format(**context)
    except KeyError:
        return template

def print_block_message(rule: Dict, command: str):
    """Print helpful block message"""
    print("\n" + "="*70, file=sys.stderr)

    # Main message
    message = rule.get('message', '❌ Command blocked')
    print(f"{message}", file=sys.stderr)

    # Reason
    if 'reason' in rule:
        print(f"\nReason: {rule['reason']}", file=sys.stderr)

    # Suggestion
    if 'suggestion' in rule:
        print(f"\n💡 Suggested Alternative:", file=sys.stderr)
        suggestion = rule['suggestion'].strip()
        for line in suggestion.split('\n'):
            print(f"   {line}", file=sys.stderr)

    # Specific alternatives
    if 'alternatives' in rule:
        print(f"\n✓ Safe Alternatives:", file=sys.stderr)
        for alt in rule['alternatives']:
            print(f"   • {alt}", file=sys.stderr)

    print("="*70 + "\n", file=sys.stderr)

def print_ask_message(rule: Dict, command: str) -> bool:
    """Print confirmation prompt and get user response"""
    print("\n" + "="*70, file=sys.stderr)

    # Message
    message = rule.get('message', '⚠️  Confirmation required')
    print(f"{message}", file=sys.stderr)

    # Prompt details
    if 'prompt' in rule:
        prompt = rule['prompt'].strip()
        print(f"\n{prompt}", file=sys.stderr)

    # Show command
    print(f"\nCommand: {command}", file=sys.stderr)

    # Reason
    if 'reason' in rule:
        print(f"Reason: {rule['reason']}", file=sys.stderr)

    print("="*70, file=sys.stderr)

    # Get confirmation
    try:
        response = input("\nProceed? [y/N]: ").strip().lower()
        return response == 'y'
    except (EOFError, KeyboardInterrupt):
        print("\n❌ Cancelled", file=sys.stderr)
        return False

# ============================================================================
# LOGGING
# ============================================================================

def log_command(command: str, status: str, reason: str = ""):
    """Log command execution"""
    log_dir = Path.home() / ".llmsec" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "intercept.log"

    timestamp = datetime.now().isoformat()
    log_entry = f"{timestamp} [{status}] {command}"
    if reason:
        log_entry += f" | {reason}"
    log_entry += "\n"

    with open(log_file, 'a') as f:
        f.write(log_entry)

# ============================================================================
# MAIN LOGIC
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: intercept-enhanced.py [--exec] <command>", file=sys.stderr)
        sys.exit(1)

    # --exec flag: check AND execute. Default: check-only (validate, return 0/1, no execution).
    exec_mode = len(sys.argv) > 1 and sys.argv[1] == '--exec'
    if exec_mode:
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    command = ' '.join(sys.argv[1:])

    # Load configuration
    try:
        config = load_permissions_config()
    except Exception as e:
        print(f"⚠️  Warning: Could not load config: {e}", file=sys.stderr)
        print("Proceeding with minimal defaults...", file=sys.stderr)
        config = {'deny': [], 'ask': [], 'allow': []}

    # Check DENY rules
    deny_rules = config.get('deny', [])
    deny_rule = find_matching_rule(command, deny_rules)

    if deny_rule:
        print_block_message(deny_rule, command)
        log_command(command, "BLOCKED", deny_rule.get('reason', ''))
        sys.exit(1)

    # Check ASK rules
    ask_rules = config.get('ask', [])
    ask_rule = find_matching_rule(command, ask_rules)

    if ask_rule:
        if not exec_mode:
            # Check-only mode: defer the prompt — log and allow through
            log_command(command, "ALLOWED_ASK_DEFERRED", ask_rule.get('reason', ''))
            sys.exit(0)
        if not print_ask_message(ask_rule, command):
            log_command(command, "DENIED_BY_USER", ask_rule.get('reason', ''))
            sys.exit(1)
        log_command(command, "APPROVED_BY_USER", ask_rule.get('reason', ''))

    # Check ALLOW rules (for logging/auditing)
    allow_rules = config.get('allow', [])
    allow_rule = find_matching_rule(command, allow_rules)

    if allow_rule:
        log_command(command, "ALLOWED", allow_rule.get('reason', ''))
    else:
        # Not explicitly allowed, but not denied either
        log_command(command, "ALLOWED_DEFAULT", "No matching rule")

    # Execute command (only in exec mode)
    if exec_mode:
        try:
            result = subprocess.run(command, shell=True)
            sys.exit(result.returncode)
        except Exception as e:
            print(f"❌ Execution error: {e}", file=sys.stderr)
            log_command(command, "ERROR", str(e))
            sys.exit(1)
    sys.exit(0)   # check-only: allowed, caller executes

if __name__ == "__main__":
    main()
