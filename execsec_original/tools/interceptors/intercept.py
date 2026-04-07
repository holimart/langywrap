#!/usr/bin/env python3
"""
Command interceptor for AI agents.
Analyzes commands and blocks dangerous ones.

Usage:
    intercept.py <command>

Environment variables:
    ENABLE_DATA_THEFT_PREVENTION - Set to 'true' to enable data exfiltration checks
"""

import sys
import re
import subprocess
import os
from datetime import datetime

# ============================================
# SYSTEM HARM PREVENTION (Always Active)
# ============================================

BLOCKED_COMMANDS = {
    'rm': ['-rf', '-fr', '-r /'],
    'dd': ['if=', 'of=/dev'],
    'mkfs': ['*'],
    'fdisk': ['*'],
    'parted': ['*'],
    'shutdown': ['*'],
    'reboot': ['*'],
    'halt': ['*'],
    'poweroff': ['*'],
    'init': ['0', '6'],
    'systemctl': ['disable', 'mask', 'stop'],
    'chmod': ['777 /', '-R 777'],
    'chown': ['-R /'],
}

DANGEROUS_PATTERNS = [
    r';\s*rm\s+-',
    r'\|\s*bash',
    r'\|\s*sh',
    r'`.*rm.*`',
    r'\$\(.*rm.*\)',
    r'base64.*\|\s*(bash|sh|eval)',
    r'eval\s+\$',
    r'>\s*/dev/(sd|hd|nvme)',
    r':\(\)\s*{\s*:\|:&\s*};:',
    r'nc\s+-[le]',
    r'/dev/(tcp|udp)/',
]

CONFIRM_COMMANDS = {
    'npm': ['install', 'i', 'ci'],
    'pip': ['install'],
    'yarn': ['add', 'install'],
    'apt': ['install', 'remove', 'purge'],
    'brew': ['install', 'uninstall'],
    'docker': ['run', 'exec', 'rm'],
    'git': ['push', 'push -f', 'reset --hard'],
}

# ============================================
# DATA THEFT PREVENTION (Optional - set env var)
# ============================================

DATA_THEFT_PATTERNS = [
    r'cat.*(\.env|credentials|\.aws|\.ssh|\.gnupg)',
    r'curl.*(-d|--data).*@',
    r'curl.*--upload-file',
    r'wget.*--post-file',
    r'base64.*(\.env|credentials|key|secret)',
    r'tar.*\.(env|ssh|aws|gnupg)',
    r'zip.*\.(env|ssh|aws|gnupg)',
    r'scp\s',
    r'rsync.*@',
    r'nc\s.*<',
    r'curl.*pastebin',
    r'curl.*transfer\.sh',
    r'curl.*file\.io',
    r'curl.*0x0\.st',
]

SENSITIVE_FILE_PATTERNS = [
    r'~?/?\.ssh/',
    r'~?/?\.aws/',
    r'~?/?\.gnupg/',
    r'~?/?\.config/gcloud',
    r'~?/?\.kube/',
    r'~?/?\.azure/',
    r'\.env',
    r'credentials',
    r'secrets?\.',
    r'.*_key(\.pem)?',
    r'.*\.pem',
    r'.*\.key',
    r'id_rsa',
    r'id_ed25519',
    r'\.npmrc',
    r'\.pypirc',
    r'\.netrc',
]

ENABLE_DATA_THEFT_PREVENTION = os.environ.get('ENABLE_DATA_THEFT_PREVENTION', 'false').lower() == 'true'

# ============================================
# ANALYSIS FUNCTIONS
# ============================================

def is_blocked(command: str) -> tuple[bool, str]:
    """Check if command should be blocked for system harm."""
    parts = command.split()
    if not parts:
        return False, ""

    cmd = parts[0]
    args = ' '.join(parts[1:])

    if cmd in BLOCKED_COMMANDS:
        blocked_args = BLOCKED_COMMANDS[cmd]
        for blocked in blocked_args:
            if blocked == '*' or blocked in args:
                return True, f"Blocked command: {cmd} with args matching '{blocked}'"

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, f"Dangerous pattern detected: {pattern}"

    return False, ""

def is_data_theft(command: str) -> tuple[bool, str]:
    """Check if command might exfiltrate data."""
    if not ENABLE_DATA_THEFT_PREVENTION:
        return False, ""

    for pattern in DATA_THEFT_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, f"Potential data exfiltration: {pattern}"

    for pattern in SENSITIVE_FILE_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            if any(op in command for op in ['cat', 'curl', 'wget', 'nc', 'scp', 'rsync', 'tar', 'zip', 'base64']):
                return True, f"Accessing sensitive file: {pattern}"

    return False, ""

def needs_confirmation(command: str) -> tuple[bool, str]:
    """Check if command needs user confirmation."""
    parts = command.split()
    if not parts:
        return False, ""

    cmd = parts[0]
    args = ' '.join(parts[1:])

    if cmd in CONFIRM_COMMANDS:
        for confirm_arg in CONFIRM_COMMANDS[cmd]:
            if confirm_arg in args:
                return True, f"{cmd} {confirm_arg}"

    return False, ""

def log_command(command: str, status: str):
    """Log command to file."""
    try:
        log_file = os.path.expanduser("~/.claude-intercept.log")
        timestamp = datetime.now().isoformat()
        with open(log_file, 'a') as f:
            f.write(f"{timestamp} [{status}] {command}\n")
    except OSError:
        pass  # Logging is best-effort; never block execution on log failure

# ============================================
# MAIN
# ============================================

def main():
    if len(sys.argv) < 2:
        print("Usage: intercept.py [--exec] <command>", file=sys.stderr)
        sys.exit(1)

    # --exec flag: check AND execute. Default: check-only (validate, return 0/1, no execution).
    exec_mode = '--exec' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--exec']
    command = ' '.join(args)

    # Check system harm
    blocked, reason = is_blocked(command)
    if blocked:
        print(f"🚫 BLOCKED (System Harm): {reason}", file=sys.stderr)
        log_command(command, "BLOCKED-HARM")
        sys.exit(1)

    # Check data theft (optional)
    theft, reason = is_data_theft(command)
    if theft:
        print(f"🔒 BLOCKED (Data Protection): {reason}", file=sys.stderr)
        log_command(command, "BLOCKED-DATA")
        sys.exit(1)

    # Check confirmation needed
    needs_confirm, what = needs_confirmation(command)
    if needs_confirm:
        if exec_mode:
            print(f"⚠️  Command requires confirmation: {what}", file=sys.stderr)
            print(f"   Full command: {command}", file=sys.stderr)
            response = input("   Execute? [y/N]: ").strip().lower()
            if response != 'y':
                print("   Cancelled.", file=sys.stderr)
                log_command(command, "CANCELLED")
                sys.exit(1)
        else:
            # Check-only mode: treat ask rules as allowed — caller will prompt if needed
            log_command(command, "ALLOWED_ASK_DEFERRED")
            sys.exit(0)

    log_command(command, "ALLOWED")
    if exec_mode:
        result = subprocess.run(command, shell=True)
        sys.exit(result.returncode)
    sys.exit(0)   # check-only: allowed, caller executes

if __name__ == "__main__":
    main()
