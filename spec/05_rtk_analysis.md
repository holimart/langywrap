# RTK (Rust Token Killer) — Technical Analysis

**Source:** https://github.com/rtk-ai/rtk  
**Version at time of analysis:** 0.34.3  
**Date:** 2026-04-06  

---

## 1. What RTK Does

RTK is a CLI proxy binary written in Rust that intercepts shell command output and compresses it before it reaches an LLM's context window. The stated goal is **60–90% token reduction** on common dev commands without changing developer or agent workflow.

In a typical 30-minute Claude Code session on a medium TypeScript/Rust project, RTK reduces approximately **118,000 tokens to ~23,900** (80% savings) across:

| Operation | Standard tokens | RTK tokens | Savings |
|-----------|-----------------|------------|---------|
| ls/tree (10x) | 2,000 | 400 | 80% |
| cat/read (20x) | 40,000 | 12,000 | 70% |
| grep/rg (8x) | 16,000 | 3,200 | 80% |
| cargo test (5x) | 25,000 | 2,500 | 90% |

This translates directly to lower API costs and longer effective context windows per session.

---

## 2. How It Works Technically

### 2.1 Execution Model

RTK operates as a transparent CLI proxy. Calling `rtk git status` causes RTK to:

1. **Parse** — Clap CLI parser extracts the subcommand and args
2. **Route** — Dispatch to the matching command module (e.g., `src/cmds/git/status.rs`)
3. **Execute** — Spawn the real subprocess and capture stdout/stderr
4. **Filter** — Apply ecosystem-specific reduction strategies
5. **Print** — Output the compressed result to stdout
6. **Track** — Write metrics to a local SQLite database

Overhead per command: **5–15ms** (benchmarked: ruff +12ms, pytest +10ms, go test +20ms).

### 2.2 Filtering Strategies (12 Types)

| Strategy | Mechanism | Reduction |
|----------|-----------|-----------|
| Stats extraction | Emit "3 files, +142/-89" summaries | 90–99% |
| Error-only | Filter stdout, keep stderr errors | 60–80% |
| Grouping by pattern | Aggregate lint violations by rule/file | 80–90% |
| Deduplication | Collapse repeated lines as "Error X (×5)" | 70–85% |
| Structure-only | JSON schema extraction without values | 80–95% |
| Code filtering (3 levels) | None / Minimal / Aggressive comment stripping | 20–90% |
| Failure focus | Hide passing tests, show failures only | 94–99% |
| Tree compression | Collapse dirs to "src/ (12 files)" | 50–70% |
| Progress filtering | Strip ANSI escape sequences | 85–95% |
| JSON/text dual mode | Prefer JSON API when tool supports it | 80%+ |
| State machine parsing | Track test lifecycle transitions | 90%+ |
| NDJSON streaming | Line-by-line event aggregation | 90%+ |

### 2.3 Command Coverage

RTK ships 50+ command handlers organised by ecosystem:

- **Files:** `ls`, `tree`, `read`, `find`, `grep`, `diff`, `json`, `log`, `wc`
- **Git:** `status`, `log`, `diff`, `add`, `commit`, `push`, `pull`, `branch` (7 ops)
- **JS/TS:** `tsc`, `next`, `lint`, `prettier`, `vitest`, `playwright`, `prisma`, `pnpm` (8 modules)
- **Python:** `ruff`, `pytest`, `pip` (3 modules)
- **Go:** `go test/build/vet`, `golangci-lint` (2 modules)
- **Rust:** `cargo build/test/check/clippy`
- **Ruby:** `rubocop`, `rspec`, `rake`
- **Containers:** `docker ps/logs/images`, `docker compose`, `kubectl pods/logs/services`
- **Packages:** `npm`, `npx`, `pip list/outdated`, `bundle install`
- **Network:** `curl`, `wget` (auto-detects JSON with schema extraction)
- **Cloud:** `aws`
- **Analytics:** `gain`, `discover`, `session`, `cc-economics`

Unknown commands fall through to a TOML filter matching system, then raw passthrough.

### 2.4 Hook System (Auto-Rewrite)

RTK's primary integration mechanism is a shell hook installed per AI tool. The hook intercepts every Bash tool call before execution, checks if a rewrite rule matches, and substitutes `git status` → `rtk git status` transparently.

Two interception modes:

- **Auto-Rewrite (default):** Hook rewrites command in-place. Agent sees only compressed output. Zero context overhead. ~100% adoption rate.
- **Suggest (non-intrusive):** Hook emits a `systemMessage` hint; agent decides. ~70–85% adoption, small context overhead.

**Important limitation:** The hook only fires on Bash tool calls. Claude Code's built-in tools (`Read`, `Grep`, `Glob`) bypass it entirely. Agents must use shell equivalents or explicit `rtk` commands for those paths.

### 2.5 Configuration System

- **Format:** TOML-based
- **Location:** `~/.config/rtk/config.toml` (Linux XDG) / `~/Library/Application Support/rtk/config.toml` (macOS)
- **Data/DB:** `~/.local/share/rtk/` (XDG-compliant), SQLite file
- **Key settings:**
  - Custom database path
  - Command exclusion list (bypass hook for specific commands)
  - "Tee mode" — preserve full output on failures for LLM recovery
  - `RTK_TELEMETRY_DISABLED=1` env var to disable analytics

### 2.6 Telemetry

Anonymous aggregate metrics collected once daily (opt-in by default): device hash, RTK version, OS, aggregated command names. Never: source code, file paths, arguments, or secrets.

---

## 3. Installation Methods

| Method | Command | Notes |
|--------|---------|-------|
| Homebrew | `brew install rtk` | Recommended for macOS |
| Quick install | `curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh \| sh` | Installs to `~/.local/bin/rtk` |
| Cargo (from git) | `cargo install --git https://github.com/rtk-ai/rtk` | Builds from source |
| Pre-built binaries | GitHub Releases page | macOS x86/arm64, Linux x86/arm64, Windows |

**Installer details:**
- Default path: `~/.local/bin/rtk` (overridable via `RTK_INSTALL_DIR`)
- Targets: `x86_64-unknown-linux-musl`, `aarch64-unknown-linux-gnu`, `{arch}-apple-darwin`
- Fetches latest release from GitHub API, downloads tarball, extracts, sets `+x`

**Name collision:** A different "rtk" package exists on crates.io (Rust Type Kit). Verify correct install with `rtk gain` — it should return token savings stats.

---

## 4. Integration Options

### 4.1 AI Tool Hook Integration

RTK ships hooks for 10+ AI coding tools. Each hook intercepts at the tool's plugin/hook boundary:

| Tool | Install Command | Mechanism | Scope |
|------|-----------------|-----------|-------|
| Claude Code | `rtk init -g` | `PreToolUse` JSON hook in `.claude/hooks/` | Global |
| GitHub Copilot | `rtk init -g --copilot` | PreToolUse hook + copilot-instructions.md | Global |
| Cursor | `rtk init -g --agent cursor` | `hooks.json` with camelCase JSON format | Global |
| Gemini CLI | `rtk init -g --gemini` | `BeforeTool` hook | Global |
| Codex | `rtk init -g --codex` | `AGENTS.md` + `RTK.md` awareness docs | Global |
| Windsurf | `rtk init --agent windsurf` | `.windsurfrules` prompt guidance | Project |
| Cline/Roo Code | `rtk init --agent cline` | `.clinerules` prompt guidance | Project |
| OpenCode | `rtk init -g --opencode` | TypeScript plugin via `zx`, `tool.execute.before` event | Global |
| OpenClaw | Via plugin install | `before_tool_call` hook | Global |

### 4.2 Claude Code Specifics

Running `rtk init -g` creates:
- `.claude/hooks/pre-tool-use.sh` — the intercepting shell hook
- Patches `.claude/settings.json` to register the hook
- Optionally writes `RTK.md` with guidance for the agent

The hook communicates via Claude Code's `PreToolUse` JSON protocol: if the command matches a rewrite rule, RTK returns the rewritten command; otherwise returns empty/pass-through.

### 4.3 Submodule / Vendoring / Dependency Options

RTK is structured as a **binary-only crate**, not a library crate. There is no published Rust library API intended for external consumption. This means:

- **Git submodule:** Possible but requires building RTK from source as part of your project's build. The Cargo workspace would need to include RTK's binary target. Practical for projects already using Rust toolchains.
- **Vendoring the binary:** The recommended approach for non-Rust projects. Download the pre-built binary during CI/setup and place it in a known path (e.g., `.exec/rtk` or `~/.local/bin/rtk`). Use `RTK_INSTALL_DIR` to control placement.
- **Cargo dependency:** Not currently published to crates.io as a usable library. `cargo install --git` installs the binary but does not expose a library API.
- **Wrapper library approach:** Since RTK is a binary proxy, wrapping it means shelling out to `rtk <cmd>` rather than linking against a Rust library. The `execwrap` / `.exec/` pattern in this template repo is the natural integration point (see section 6).

---

## 5. License

**License:** Apache License 2.0  
**Copyright:** 2024 rtk-ai and rtk-ai Labs  
**Cargo.toml declares:** MIT (minor discrepancy — the LICENSE file is Apache 2.0)

Apache 2.0 permits: use, modification, distribution, sublicensing, private use. Requires: preservation of copyright notice, license text, and NOTICE file if present. No copyleft provisions.

---

## 6. Incorporating RTK into a Wrapper Library

### 6.1 Recommended Integration Pattern

Since RTK is a binary (not a Rust library crate), the integration strategy is:

1. **Bundle/vendor the binary** — add to `.exec/rtk` using the install script or a pinned release download
2. **Detect and use automatically** — in the wrapper's shell hook, check if `rtk` is on PATH; if yes, prepend commands automatically
3. **Install the Claude Code hook** — run `rtk init -g` once, or manually write the hook script to `.claude/hooks/pre-tool-use.sh`
4. **Provide fallback** — if `rtk` is absent, pass commands through unmodified

### 6.2 Integration with llmtemplate's execwrap Pattern

The `.exec/` universal wrapper in this template repo is the ideal location:

```
.exec/
  rtk          ← vendored RTK binary (platform-specific)
  settings.json ← unified tool settings
  run           ← execwrap entry point
```

The `pre-tool-use.sh` hook can source `.exec/rtk` or fall back to `$(which rtk)`:

```bash
RTK_BIN="${EXEC_DIR:-$PWD/.exec}/rtk"
if [ ! -x "$RTK_BIN" ]; then
    RTK_BIN="$(which rtk 2>/dev/null)"
fi
```

### 6.3 RTK.md Instruction Injection

RTK provides an `RTK.md` file containing guidance for agents. For a wrapper library:
- Include `RTK.md` content in the project's `CLAUDE.md` or as a separate rules file
- Key instruction: prefer `rtk <cmd>` over raw commands for all supported operations
- This drives adoption on the "Suggest" hook path (70–85% vs 100% for auto-rewrite)

### 6.4 OpenCode-Specific Integration

For OpenCode integration (relevant to this template's ralph loop):

```typescript
// TypeScript plugin using zx — hooks tool.execute.before event
// Mutates tool arguments in-place before execution
// Installed to: ~/.opencode/plugins/rtk/
```

Run `rtk init -g --opencode` to install. The OpenCode plugin uses the `zx` library and fires on `tool.execute.before`, directly modifying command arguments.

---

## 7. API and Configuration Surface

### 7.1 Rust Public API (for source-level integration)

RTK is not designed as a library, but its internal modules expose:

**`src/core/filter.rs`**
```rust
pub enum FilterLevel { None, Minimal, Aggressive }
pub enum Language { Rust, Python, JavaScript, TypeScript, Go, C, Cpp, Java, Ruby, Shell, Data, Unknown }
pub trait FilterStrategy { fn filter(&self, content: &str, lang: &Language) -> String; }
pub fn get_filter(level: FilterLevel) -> Box<dyn FilterStrategy>
pub fn smart_truncate(content: &str, max_lines: usize, lang: &Language) -> String
impl Language {
    pub fn from_extension(ext: &str) -> Self
    pub fn comment_patterns(&self) -> CommentPatterns
}
```

**`src/core/utils.rs`**
```rust
pub fn truncate(s: &str, max_len: usize) -> String
pub fn strip_ansi(text: &str) -> String
pub fn format_tokens(n: usize) -> String           // "1.2M" formatting
pub fn format_usd(amount: f64) -> String
pub fn detect_package_manager() -> &'static str    // npm/yarn/pnpm/bun
pub fn package_manager_exec(tool: &str) -> Command
pub fn tool_exists(name: &str) -> bool
pub fn resolve_binary(name: &str) -> Result<PathBuf>
```

**`src/core/tracking.rs`**
```rust
pub struct Tracker { /* SQLite-backed */ }
impl Tracker {
    pub fn new() -> Result<Self>
    pub fn record(original_cmd, rtk_cmd, input_tokens, output_tokens, exec_time_ms) -> Result<()>
    pub fn get_summary_filtered(project_path: Option<&str>) -> Result<GainSummary>
    pub fn get_all_days_filtered(project_path: Option<&str>) -> Result<Vec<DayStats>>
}
pub struct TimedExecution;
impl TimedExecution {
    pub fn start() -> Self
    pub fn track(&self, ...) -> Result<()>
    pub fn track_passthrough(&self, ...) -> Result<()>
}
```

**Token counting formula:** `tokens = ceil(chars / 4.0)` (4 chars ≈ 1 token approximation)

### 7.2 CLI Global Flags

```
-v / --verbose       Verbosity: -v (debug), -vv (show command), -vvv (raw output before filter)
-u / --ultra-compact ASCII icons, inline format for maximum compression
--skip-env           Skip environment validation (SKIP_ENV_VALIDATION=1)
```

### 7.3 Database Schema

SQLite at `~/.local/share/rtk/rtk.db` (XDG):

```sql
CREATE TABLE commands (
    timestamp     TEXT,   -- RFC3339 UTC
    original_cmd  TEXT,
    rtk_cmd       TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    saved_tokens  INTEGER,
    savings_pct   REAL,
    exec_time_ms  INTEGER,
    project_path  TEXT    -- cwd, empty string if not set
);
CREATE TABLE parse_failures ( ... );
```

Retention: 90-day automatic cleanup. WAL mode with 5-second busy timeout.

### 7.4 Environment Variables

| Variable | Effect |
|----------|--------|
| `RTK_INSTALL_DIR` | Override install directory (default `~/.local/bin`) |
| `RTK_TELEMETRY_DISABLED=1` | Disable anonymous telemetry |
| `SKIP_ENV_VALIDATION=1` | Skip environment checks in subprocesses |

### 7.5 Analytics Commands

```
rtk gain [--graph] [--daily] [--history]   Token savings summary
rtk discover                                Identify missed optimization opportunities
rtk session                                 RTK adoption metrics across recent sessions
rtk cc-economics                            Claude Code cost/savings analysis
```

---

## 8. Adding New Commands (Extensibility)

RTK's ARCHITECTURE.md documents the extension pattern:

1. Create module at `src/cmds/{ecosystem}/{command}.rs`
2. Implement `pub fn run(args: &[String], verbose: u8) -> anyhow::Result<()>`
3. Register variant in `Commands` enum in `main.rs`
4. Integrate tracking: `tracking::track(...)`
5. Add verbosity guards: `if verbose > 0 { eprintln!(...) }`

Format strategy decision tree:
- Tool supports `--json` flag → use JSON API
- Streaming events (NDJSON) → parse line-by-line
- Plain text only → state machine or text filter regex

Module checklist: failure-only output, exit code propagation, virtualenv awareness (Python), error grouping (linters), streaming support, verbosity levels, token tracking, unit tests.

---

## 9. Summary Assessment for llmtemplate Integration

| Concern | Assessment |
|---------|------------|
| License compatibility | Apache 2.0 — permissive, safe for bundling |
| Binary size | Single stripped Rust binary, typically <5MB |
| Dependencies | Zero runtime deps; SQLite and stdlib only |
| Platform support | Linux x86/arm64, macOS x86/arm64, Windows |
| Submodule viability | Low — binary tool, not a library; vendoring preferred |
| Wrapper library fit | High — shell-out pattern; `.exec/rtk` placement natural |
| Claude Code integration | Native via `PreToolUse` hook; `rtk init -g` installs it |
| OpenCode integration | Native TypeScript plugin; `rtk init -g --opencode` |
| Configuration surface | TOML config, env vars, per-tool hook files |
| Overhead | 5–15ms per command; negligible |
| Active development | v0.34.3; Discord community; frequent releases |

**Recommended integration path:** Vendor the platform binary to `.exec/rtk` via the install script during project bootstrap. Register the Claude Code `PreToolUse` hook automatically in `execwrap-setup`. Inject `RTK.md` content into `CLAUDE.md` to drive agent adoption. This requires no source-level Rust integration.
