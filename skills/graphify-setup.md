---
description: Install and wire Graphify (code knowledge graph) into a langywrap-coupled repo — choose ONE delivery channel (prompt enrichment, MCP, or PreToolUse hook) to avoid triple-enrichment token waste
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
---

# Graphify Setup Skill

Wire [Graphify](https://github.com/safishamsi/graphify) into a langywrap-coupled
repository. Graphify builds a queryable knowledge graph over code + docs +
papers + images and exposes it to AI coding agents, reducing per-query token
cost on large/multi-modal repos.

Target directory: **$ARGUMENTS** (default: current working directory).

**Important:** Graphify can feed the model through **three** channels. Pick
exactly **one** — enabling more than one duplicates context and wastes tokens.
langywrap's RalphLoop emits a startup warning if ≥2 are active; this skill
prevents that misconfiguration up front.

---

## PHASE 0 — Decide fit before installing

Graphify helps **planning / impact review**, rarely **code execution**. If the
target repo is small (<500 files) or single-language Python without docs/papers,
Graphify's overhead likely exceeds its benefit — Aider-style repomap or plain
grep is cheaper. Check:

```bash
# File count + modality mix
find "$TARGET" -type f \
  \( -name '*.py' -o -name '*.ts' -o -name '*.go' -o -name '*.rs' \
     -o -name '*.md' -o -name '*.pdf' -o -name '*.png' -o -name '*.mp4' \) \
  | wc -l
```

Recommend Graphify when: ≥500 relevant files, OR mixed modalities (code + docs
+ papers/images), OR the agent is repeatedly burning tokens on `Grep`/`Glob`
fan-out.

If the repo fails the heuristic, **stop here** and report back. Do not install.

---

## PHASE 1 — Install Graphify + Textify via langywrap

Both ship as **vendored submodules** of langywrap (`graphify/` and `textify/`)
and are installed by langywrap's top-level installer. Downstream repos that
couple to langywrap inherit them for free — there is no per-repo install step.

```bash
# From the langywrap root (once per langywrap checkout):
./just install              # Installs everything including graphify + textify
# Or just the two:
./just install-textify
./just install-graphify
```

The installer pins graphify to the submodule's committed version (currently
`v0.4.21`). Bump by `git submodule update --remote graphify` + commit when you
want a newer release.

Verify:

```bash
command -v graphify && command -v textify
```

If either is missing after `./just install`, the wizard likely had the step
opted out — rerun `./install.sh` and enable both.

**No runtime install:** the ralph runner never installs Python packages
mid-loop. If a binary is missing at loop start, the preflight warns once and
points at `./just install` — the operator fixes it and reruns. Optionality
lives entirely in the pipeline config (whether steps declare `enrich=['graphify']`
and whether `post_cycle_commands` invokes the rebuild), not in runtime install
logic.

### Build the graph once — LLM-FREE protocol

Graphify's default `graphify .` build invokes **LLM subagents** (via the host
coding assistant) for PDFs, DOCX, images, and other non-code files. To stay
token-free, follow this protocol:

```bash
cd "$TARGET"

# 1. Flatten every binary/office/image doc to plain text. NO LLM. Deterministic.
textify docs graphify-in/docs

# 2. Tell Graphify to skip the raw binaries — it will only see code + the
#    text mirror that textify produced.
cat >> .graphifyignore <<'EOF'
# Exclude raw non-code so Graphify never invokes LLM for doc extraction.
docs/**/*.pdf
docs/**/*.docx
docs/**/*.xlsx
docs/**/*.png
docs/**/*.jpg
docs/**/*.jpeg
docs/**/*.webp
docs/**/*.mp4
docs/**/*.mov
docs/**/*.mp3
EOF

# 3. Initial full build — LLM-free because textify pre-flattened everything
#    and .graphifyignore excluded the originals.
graphify .
```

**If you skip step 1 and keep raw binaries visible**, `graphify .` WILL consume
tokens. The ralph preflight prints a warning in that case.

**After the initial build, the ralph loop uses `graphify update .`** — that
subcommand is explicitly code-only and documented as "no LLM needed" by graphify
itself. See Phase 2 Channel A below for the `post_cycle_commands` wiring.

Outputs land in `graphify-out/`:
- `graph.html` — interactive visualization
- `GRAPH_REPORT.md` — god nodes + communities (langywrap reads this)
- `graph.json` — persistent graph
- `cache/` — SHA256 incremental cache

Add to `.gitignore`:

```
graphify-out/
graphify-in/   # textify output tree (if used)
```

### Ask: git post-commit hook?

Graphify ships an optional post-commit hook (`graphify hook install`) that
incrementally rebuilds the graph on every commit. **It's one of two update
channels** — pick one, not both:

- **Hook (commit-triggered)** — fires only when a commit lands. Misses updates
  in long-running ralph cycles that haven't committed yet. Best for human-driven
  IDE sessions.
- **`post_cycle_commands` (cycle-triggered)** — fires at the end of every ralph
  iteration regardless of commit. Keeps the graph fresh inside a running loop.
  Recommended for ralph loops (see Phase 2).

Use `AskUserQuestion` to let the user choose:
- "Install Graphify post-commit hook?" → yes / no / "only post_cycle_commands"

If they pick the hook, run: `cd "$TARGET" && graphify hook install`.
If they pick post-cycle only, skip the hook and proceed to Phase 2.

---

## PHASE 2 — Pick ONE delivery channel

Ask the user (or pick based on context) which channel fits their workflow:

### Channel A — Prompt enrichment (recommended for ralph loops)

**Best for:** langywrap ralph loops, multi-model pipelines, hyperagent evolution.
**Cost:** One file read per step, capped at 20KB. Deterministic. No per-tool-call latency.
**Downside:** Static snapshot; stale after execute-phase code changes — solved
by the `post_cycle_commands` rebuild below.

Edit `.langywrap/ralph.py`:
1. Add `enrich=['graphify']` **only** to planning / critic steps (skip execute;
   grep beats graphs there per SWE-bench).
2. Add `post_cycle_commands` so every iteration ends with a fresh, LLM-free
   rebuild — textify flattens docs, graphify incrementally re-parses code.

```python
from langywrap.ralph.pipeline import Pipeline, Step, Gate

config = Pipeline(
    prompts="research/prompts",
    steps=[
        Step("orient",  model="haiku", prompt="orient.md",  enrich=["graphify"]),
        Step("plan",    model="sonnet", prompt="plan.md",   enrich=["graphify"]),
        Step("execute", model="kimi",   prompt="execute.md"),   # NO enrich
        Step("critic",  model="sonnet", prompt="critic.md",  enrich=["graphify"]),
        Step("finalize", model="kimi",  prompt="finalize.md"),
    ],
    gates=[Gate("./just check")],
    post_cycle_commands=[
        # 1. Flatten any new/changed binary docs to plain text. No LLM.
        "textify docs graphify-in/docs || true",
        # 2. Code-only incremental update. Graphify's `update <path>` subcommand
        #    is explicitly LLM-free (tree-sitter AST re-extraction only).
        #    Do NOT use `graphify .` here — that's a full build and invokes
        #    LLM subagents for any docs/images/PDFs the walker finds.
        "graphify update .",
    ],
    post_cycle_command_timeout=120,
)
```

Post-cycle commands run **after quality gates and before git commit**, so the
refreshed `graphify-out/` stages alongside the code changes that triggered the
rebuild. Non-zero exits are warnings — a broken indexer never fails the cycle.

### Channel B — MCP server (for mixed tool use)

**Best for:** agents that should query the graph interactively (e.g. BFS
subgraph lookup, shortest-path between modules).
**Cost:** Per-query round-trip, but only when the model asks.
**Downside:** Not all backends support MCP (OpenCode yes; Claude CLI via settings).

Edit `.langywrap/mcp.json`:

```json
{
  "mcpServers": {
    "graphify": {
      "command": "graphify",
      "args": ["serve", "graphify-out/graph.json"]
    }
  }
}
```

langywrap's `mcp_config.sync_langywrap_mcp_manifest` auto-propagates this to
`opencode.json` on next ralph run.

### Channel C — PreToolUse hook (use with caution)

**Best for:** interactive Claude Code sessions where the human (not a loop)
drives the search.
**Cost:** Fires on EVERY `Glob`/`Grep` call — very expensive in ralph loops.
**Downside:** Effectively disqualifies itself for autonomous loops.

Run Graphify's own installer (it writes the hook to the per-project settings):

```bash
graphify claude install
```

**Do not enable this channel if Channel A is active** on the same repo.

---

## PHASE 3 — Verify + warn check

Run a single dry-cycle of the ralph loop and confirm the triple-enrichment
warning does NOT fire:

```bash
cd "$TARGET"
./uv run python -c "
from pathlib import Path
from langywrap.ralph.context import detect_enrichment_channels
from langywrap.ralph.pipeline import load_pipeline_config

p = load_pipeline_config(Path('.'))
steps = [list(s.enrich) for s in p.steps] if p else []
flags = detect_enrichment_channels(Path('.'), steps)
active = [k for k, v in flags.items() if v]
print('Graphify channels active:', active)
assert len(active) <= 1, f'Triple-enrichment detected: {active}'
print('OK — single channel')
"
```

If the assertion fails, the user has wired Graphify through multiple paths.
Disable all but one before proceeding.

---

## PHASE 4 — Document in AGENTS.md / CLAUDE.md

Append a short note to the target repo's AGENTS.md (or CLAUDE.md) so downstream
agents know the graph exists and which channel is authoritative:

```markdown
## Graphify knowledge graph

Code + doc knowledge graph in `graphify-out/`. Rebuild with `graphify --update`
(or let the git post-commit hook do it).

- Delivery: **<A | B | C>** (pick the one actually configured).
- Capped at 20KB when injected via prompt enrichment.
- Do NOT enable on the `execute` step — grep+read is cheaper there.
```

---

## Done

Report to the user:
1. Which channel was chosen (A/B/C) and why.
2. Graph build stats: `du -sh graphify-out/` and node/edge count from `GRAPH_REPORT.md`.
3. Confirmation that the single-channel check passed.
4. Next action: run `./just ralph` (or equivalent) for a first cycle and eyeball
   whether the orient step actually references graph content.

Do NOT install Graphify via more than one channel. If the user insists on
multiple channels, they can override the startup warning — but flag the extra
token cost explicitly.
