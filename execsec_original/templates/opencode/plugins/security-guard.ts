// Security guard plugin for OpenCode's tool.execute.before hook
// - Audit logs every command attempt
// - Blocks data exfiltration patterns
// - Provides helpful messages for dangerous patterns
//
// Throwing an error blocks the command execution.
//
// Template variables:
//   __PROJECT_NAME__ - replaced with project name during installation

import { appendFileSync, mkdirSync, existsSync } from "fs";
import { join } from "path";

const PROJECT_NAME = "__PROJECT_NAME__";
const LOG_DIR = join(process.env.HOME || "~", ".llmsec", "logs");
const LOG_FILE = join(LOG_DIR, `${PROJECT_NAME}_audit.log`);

function ensureLogDir(): void {
  if (!existsSync(LOG_DIR)) {
    mkdirSync(LOG_DIR, { recursive: true });
  }
}

function logEntry(status: string, command: string): void {
  ensureLogDir();
  const timestamp = new Date().toISOString();
  appendFileSync(LOG_FILE, `${timestamp} | ${status} | ${command}\n`);
}

function block(command: string, message: string): never {
  logEntry("BLOCKED", command);
  throw new Error(message);
}

// Data theft patterns
const EXFIL_SERVICES = /(?:curl|wget|http).*(?:pastebin\.com|transfer\.sh|file\.io|paste\.ee|hastebin|0x0\.st|ix\.io)/i;
const BASE64_SECRETS = /base64.*(?:\.env|credentials|_key\.pem|id_rsa|id_ed25519|\.aws)/i;
const CAT_SECRETS = /(?:cat|tar|zip|gzip|7z)\s.*(?:\.env|\.ssh\/|\.aws\/|credentials|_key\.pem|id_rsa|id_ed25519|\.gnupg)/i;
const SCP_SECRETS = /(?:scp|rsync)\s.*(?:\.env|\.ssh|\.aws|credentials|_key\.pem)/i;

// Dangerous command patterns
const RM_RECURSIVE = /(?:^|\s|;|&&|\|)rm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f?|(?:-[a-zA-Z]*f[a-zA-Z]*)?-[a-zA-Z]*r)\s/;
const SUDO = /(?:^|\s|;|&&|\|)sudo\s/;
const CHMOD_777 = /chmod\s+777/;
const DD = /(?:^|\s|;|&&|\|)dd\s/;
const FORCE_PUSH = /git\s+push\s+.*(?:-f|--force)/;

export default {
  name: "security-guard",

  "tool.execute.before"(event: { tool: string; input: Record<string, unknown> }): void {
    if (event.tool !== "bash" && event.tool !== "shell") return;

    const command = (event.input.command as string) || "";
    if (!command) return;

    // Data theft prevention
    if (EXFIL_SERVICES.test(command)) {
      block(command,
        "BLOCKED: Data exfiltration attempt detected.\n" +
        "Reason: Command appears to send data to an external paste/upload service.\n" +
        "Suggestion: Write output to a local file instead.");
    }

    if (BASE64_SECRETS.test(command)) {
      block(command,
        "BLOCKED: Encoding sensitive file detected.\n" +
        "Reason: Base64-encoding secrets could facilitate exfiltration.\n" +
        "Suggestion: Reference secrets via $ENV_VAR, don't read files directly.");
    }

    if (CAT_SECRETS.test(command)) {
      block(command,
        "BLOCKED: Access to sensitive file detected.\n" +
        "Reason: Reading/archiving credentials, keys, or secrets is not permitted.\n" +
        "Suggestion: Use environment variables to reference secrets.");
    }

    if (SCP_SECRETS.test(command)) {
      block(command,
        "BLOCKED: Transfer of sensitive files detected.\n" +
        "Reason: Copying credentials or keys to remote hosts is not permitted.\n" +
        "Suggestion: Use secure secret management (vault, env vars) instead.");
    }

    // Dangerous patterns
    if (RM_RECURSIVE.test(command)) {
      block(command,
        "BLOCKED: Recursive delete (rm -rf / rm -r) is not allowed.\n" +
        "Reason: Recursive deletion is destructive and hard to reverse.\n" +
        "Suggestion: Move files to trash: mv <path> /tmp/trash/");
    }

    if (SUDO.test(command)) {
      block(command,
        "BLOCKED: sudo (privilege escalation) is not allowed.\n" +
        "Reason: Running commands as root can cause system-wide damage.\n" +
        "Suggestion: Work within current user permissions.");
    }

    if (CHMOD_777.test(command)) {
      block(command,
        "BLOCKED: chmod 777 is not allowed.\n" +
        "Reason: World-writable permissions are a security vulnerability.\n" +
        "Suggestion: Use chmod 644 (files) or chmod 755 (directories).");
    }

    if (DD.test(command)) {
      block(command,
        "BLOCKED: dd (disk/data duplicator) is not allowed.\n" +
        "Reason: dd can overwrite disks and cause irreversible data loss.\n" +
        "Suggestion: Use cp for file copying.");
    }

    if (FORCE_PUSH.test(command)) {
      block(command,
        "BLOCKED: Force push is not allowed.\n" +
        "Reason: Force pushing overwrites remote history.\n" +
        "Suggestion: Use regular 'git push' or --force-with-lease.");
    }

    // Command allowed
    logEntry("ALLOWED", command);
  },
};
