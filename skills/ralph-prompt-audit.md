---
description: Deep LLM-level audit of a ralph project's prompts and pipeline config for contract drift the static regex audit cannot catch. Reads every step prompt, the `ralph.py` pipeline definition, and `langywrap/ralph/runner.py` semantics, then reports semantic mismatches (e.g. inputs read but never produced upstream, tools the step uses but is not granted, confirmation tokens that the model has no incentive to emit, sub-agent briefs referenced but missing). The static `prompt_audit.py` rules (PROMPT_WRITES_RUNNER_FILE, CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK, …) only catch shape; this skill catches meaning. Use whenever `ralph run --dry-run` reports any audit finding, before non-trivial prompt edits, or after a model swap.
allowed-tools: Read, Glob, Grep, Bash(rg:*, fd:*, find:*, ls:*, wc:*, python3:*)
---

# Ralph Prompt + Pipeline Contract Audit (semantic)

Static regex rules in `langywrap/ralph/prompt_audit.py` catch the
shape-level bugs: missing tokens, Write directives clobbering
runner-owned files, plan validators with no producer. This skill
catches **meaning-level** bugs the regex can't see, by reading the
whole pipeline like a reviewer would.

## When to run

- Preflight (`uv run langywrap ralph run --dry-run`) emitted any
  `[ERROR]` or `[WARN]` finding.
- You're about to change a prompt the loop depends on
  (`step1_orient.md`, `step4_finalize.md`, any `step3_execute_*.md`).
- A model alias just changed (e.g. `gpt-5.2 → gpt-5.4`); semantic
  contracts that worked for one model can rot under another.
- After resolving a `consecutive_failed_cycles` stop, before
  re-enabling the loop.
- A cycle hard-failed in `inline_orient`'s preflight lint with
  `unified_format` on a `tasks.md` line the loop itself just
  wrote (template/lint coherence drift — run check J).
- You edited `Periodic(...)` entries in `.langywrap/ralph.py`,
  any `template=` string, or langywrap's `pipeline.py` /
  `state.py` injection logic (run check J).

## Arguments

`$ARGUMENTS` — optional path to the project root containing
`.langywrap/ralph.py` and `ralph/prompts/*.md`. Defaults to the
current working directory.

## Inputs to read (in this order)

1. **The pipeline definition** — `${PROJECT}/.langywrap/ralph.py`.
   Note every `Step(…)` definition: name, model, engine, tools,
   confirmation_token, output_as, validates_plan, depends_on,
   run_if, fail_fast, timeout. Treat aliases as authoritative for
   model identity.
2. **Each step prompt** — `${PROJECT}/ralph/prompts/*.md`. Read in
   full; do not skim.
3. **The runner contract** —
   `/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/runner.py`,
   specifically the `# Save output to steps/{step.name}.md (per-step
   debug log).` comment (~line 447) and `_check_token` usage. Many
   prompt bugs trace back to misunderstanding this contract.
4. **The static audit module** —
   `/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/prompt_audit.py`.
   The semantic checks below extend, not replace, the rules there.
5. **The lint contract** (only when running check J) —
   `/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/lint_tasks.py`
   for `UNIFIED_TASK_LINE_RE` and the `unified_format` rule,
   `/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/pipeline.py`
   for `Periodic → RalphConfig` wiring, and
   `/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/state.py`
   for `inject_*_task` fallback strings.

## Semantic checks (each one a section in your report)

For each, output PASS / WARN / FAIL with file:line citations.

### A. Confirmation-token reachability
For every step with a `confirmation_token`:
- Does the prompt instruct the model in a way that naturally produces
  the token in its **stdout reply** (not via a Write tool to
  `ralph/steps/<X>.md`)? A `Write \`ralph/steps/<X>.md\`:` directive
  alone is FAIL — see
  `docs/solutions/2026-05-12_ralph_finalize_confirmation_token_lost_to_write_clobber.md`.
- If the prompt does instruct a Write, is there ALSO an explicit
  "End your reply with…" / "in your stdout response" / "first
  non-blank line of your reply" directive? If not, FAIL.

### B. Tool/grant agreement
For each step:
- Cross-reference the operations the prompt asks for ("clone…",
  "WebFetch…", "build…", "edit…") against the `tools=[…]` list in
  `ralph.py`. Each verb must map to an allowed tool. FAIL on
  mismatch (e.g. prompt asks for `git clone` but no `Bash` tool).
- If `engine="opencode"`, note that the `tools` argument is advisory
  (per-call allowlist is Claude-CLI-only); the prompt must
  self-discipline. Flag prompts that rely on tool-grant enforcement
  for safety as WARN.

### C. Input chain integrity
For each input file the prompt declares (typically under
`## Inputs`):
- Trace upstream: is there a step earlier in the pipeline whose
  prompt instructs the model to **Write** that file (canonical
  state) OR is it a runner-owned `ralph/steps/<X>.md` the runner
  mirrors from a prior step's stdout?
- If neither, FAIL — the input is referenced but never produced.
  This was the historical ktorobi `plan.md` regression
  (see `WRITE_PLAN_TARGET` rule).

### D. Sub-agent brief existence
For every prompt mentioning `.claude/agents/<name>.md`, verify the
file exists and is readable. FAIL on missing brief.

### E. Output-template grammar
For each step's output block (template ending with
`---` after the confirmation token):
- Are the field names referenced by downstream steps (grep
  downstream prompts for the exact field names) actually emitted by
  this template? E.g. finalize reads `template_complete:` and
  `mainnet_exposure_value:` — they must be in
  `step3_execute_repro.md`'s output template.
- Are CONDITIONAL output fields gated on the same conditions the
  downstream consumer expects? Misaligned gating ≈ silent
  divergence.

### F. Model-suitability sanity
For each step's `model`:
- Note context-window budget: short-context models (gpt-5.4-mini)
  can't carry 200k-char prompts. FAIL if `Prompt: <N> chars` in
  recent logs would exceed the model's window (or close enough that
  truncation is plausible — within 20% of advertised window).
- Note response-length budget: `finalize` historically used
  gpt-5.2 with high reasoning effort; a 600B narrative reply is the
  expected tell that the model is summarizing rather than echoing
  templates. If a step's confirmation-token homing depends on
  template echo (cf. check A), and the model is configured for
  terse output, FLAG.

### G. Cycle-type label coverage
If `ralph.py` defines `detects_cycle=Match(...)` (or
`cycle_type_rules` directly), every label in the union must appear
literally in the cycle-type source prompt. The static rule
`CYCLE_TYPE_LABEL_NOT_IN_SOURCE_PROMPT` covers this — verify it is
firing iff intended.

### H. `tasks.md` write coordination
If two or more steps write `ralph/tasks.md` in the same cycle
(e.g. execute appends a task, finalize re-orders), the prompts must
agree on append vs in-place edit semantics. Last-write-wins on
`tasks.md` has been a real silent-loss vector.

### I. Supersafe scope drift
Project-specific: for `whitehacky`, grep each prompt for
`KYC | live targeting | mainnet traffic | destructive | submission`.
Cross-check against the case's `legal_triage.md` posture flag set in
`step3_execute_caseinit.md`. FAIL if a step could trigger a
gated action without the matching posture check.

### J. Task-injection template ↔ lint coherence
The runner periodically writes new tasks into `ralph/tasks.md`
(hygiene, lookback, adversarial, custom periodics) and then the
**same** `tasks.md` is preflight-linted at the top of every cycle.
A mismatch between the templates that emit checkbox lines and the
lint rule that validates them is a silent foot-gun: the loop will
inject a malformed line, then hard-fail its own preflight on the
next cycle. We have hit this in production (see
`docs/solutions/2026-05-12_hygiene_template_dropped_by_pipeline.md`
if present, or the ktorobi cycle-150 incident in git log).

Run these sub-checks per project:

**J.1 — Lint contract (read once)**

Open
`/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/lint_tasks.py`
and capture:
  - `UNIFIED_TASK_LINE_RE` and `CHECKBOX_PREFIX_RE` (the shape
    every checkbox line must satisfy).
  - The error message at the `rule="unified_format"` finding
    (`- [ ] **[Pn] task:slug** [task_type] label`) — this is the
    authoritative format string.
  - `LintConfig.allowed_task_types` and `allowed_priorities`
    defaults, plus any project override in
    `.langywrap/lint.yaml` / `ralph.py`.

**J.2 — Project template shape**

In `${PROJECT}/.langywrap/ralph.py`, locate every
`Periodic(...)` definition. For each `Periodic` with a `template=`
argument, expand the template with placeholder values
(`{cycle}=999`, `{date}=2099-01-01`,
`{quality_gate_cmd}=run quality checks`) and verify the **first
non-blank line** matches `UNIFIED_TASK_LINE_RE` AND uses an allowed
priority + task_type. FAIL on mismatch — quote the rendered line
and the rule message.

Common bug: template starts with `- [ ] **[P2] <Label>**` with no
`task:<slug>` segment and no `[<task_type>]` tag. This is the exact
shape `state.py`'s fallback emits when the project template is
silently dropped.

**J.3 — Library fallback shape**

In `/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/state.py`,
read `inject_hygiene_task` (around line 305) and any sibling
`inject_*` injectors. If the function has a fallback branch
(`if template: ... else: <inline string>`), the inline string must
also satisfy `UNIFIED_TASK_LINE_RE`. A library fallback that
violates the lint rule is a latent footgun for every downstream
project that forgets to pass `template=`. FAIL — patch the
fallback or delete it in favor of a hard error.

**J.4 — Pipeline wiring (template plumbed through?)**

In
`/mnt/work4t/Projects/langywrap/lib/langywrap/ralph/pipeline.py`,
locate the `for p in self.periodic:` loop. For **every** branch
(`builtin == "hygiene"`, `builtin == "lookback"`, `p.step`,
`p.template` only), verify:
  - `p.template` is captured into a local that is then forwarded to
    `RalphConfig(...)` (e.g. `hygiene_template=hygiene_template`),
    OR appended to `periodic_tasks` with `"template": p.template`.
  - The matching field exists on `RalphConfig` (check `config.py`).
  - The runner reads that field when injecting
    (check `runner.py` around lines 150–200).

FAIL if a `Periodic` builtin captures `p.every` but discards
`p.template` (this was the ktorobi cycle-150 root cause). The
project template silently becomes empty and the library fallback
takes over.

**J.5 — Live tasks.md sanity**

In `${PROJECT}/ralph/tasks.md`, grep the last 30 checkbox lines
and confirm each matches `UNIFIED_TASK_LINE_RE`. If any do not,
WARN with line number and quote — the next preflight will hard-fail.
(This is a runtime tripwire complementing J.2–J.4: if the static
audit passes but live state is dirty, the loop has already drifted.)

**J.6 — Marker uniqueness**

For each periodic injection, the runner uses a marker comment
(`<!-- hygiene-cycle-N -->`) for dedup. WARN if two checkbox lines
in `tasks.md` share the same marker, or if a template emits no
marker at all (silent dedup failure → duplicate injections every
cycle).

Cite all findings under `### [FAIL|WARN] task-injection — J.<n>
<title>` and tie each to a concrete failure mode (cycle that
hard-failed, duplicate task, or "next preflight will break").

## Output format

End your reply with a single Markdown report:

```markdown
# Ralph Contract Audit — <project> — <date>

## Summary
- Checks run: 10
- FAIL: <N>
- WARN: <N>
- PASS: <N>

## Findings (FAIL first, then WARN)

### [FAIL] <step name> — <check letter> <check title>
**Evidence:** <prompt file:line + quoted snippet>
**Why it matters:** <one paragraph; tie back to a concrete failure
mode, ideally with a log path or commit hash if one exists>
**Suggested fix:** <one paragraph, actionable>

(repeat per finding)

## Coverage gaps
<things the audit could not verify without runtime evidence — list
the log files an operator should consult next>
```

After the report, exit. Do NOT use the Write tool to persist the
report (this skill is read-only by design — the user owns the
follow-up edits). If the user wants the report kept, they can
redirect the output to a file.

## How preflight points here

`langywrap/ralph/runner.py` prints
`[prompt audit] N error(s), M warning(s):` followed by the rule
hits. The runner now appends a one-liner pointing operators at this
skill when *any* finding is present:

```
For a deeper semantic audit (input chains, tool grants, model
suitability), run:
  claude /ralph-prompt-audit
or
  opencode run "/ralph-prompt-audit ${PROJECT_ROOT}"
```

Operators should run the static audit first, fix the easy
regex-detectable issues, then run this skill to catch the
shape-passes-but-semantics-don't class of bugs.
