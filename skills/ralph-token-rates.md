---
description: Calculate input/output tokens-per-second usage from ralph loop logs. Parses `step_finish` events emitted by opencode-backed steps and pairs them with `COMPLETED` durations in master logs. Distinguishes agent-throughput (what we measure) from model-decode-throughput (what providers publish).
allowed-tools: Read, Glob, Grep, Bash(python3:*, ls:*, wc:*)
---

# Ralph Token Rate Analysis

Calculate how many input/output/cache tokens per second a ralph loop consumes while active. Works on any repo that uses langywrap's ralph runner and writes logs to `research/ralph/logs/` (or another configured `state` dir).

## What this skill measures vs what it does NOT measure

**You will compute `agent throughput`** = `tokens / wall_clock`, which folds in:

- model prefill (compute-bound, parallel — usually 1k–10k tok/s)
- model decode (sequential — Kimi K2.5 ≈ 50–100 tok/s on tuned hardware, much less on shared NIM; GPT-5.2 ≈ 30–70 tok/s)
- **tool execution time** (e.g. `lake build`, file reads — often 30–500s per turn in a Lean loop)
- network + queueing + provider rate-limit waits

This is the right number for **capacity planning, cost estimation, and quota sizing**. It is the **wrong** number for "is the model fast enough" — for that, compute inter-token-latency (ITL) on tool-free turns.

Industry convention separates **TTFT** (time-to-first-token), **ITL** (`(end − TTFT)/(out − 1)`), and **task throughput**. Agent loops typically show 2–10× lower output tok/s than raw decode, because tool calls dominate wall-clock. See: [Anyscale LLM metrics](https://docs.anyscale.com/llm/serving/benchmarking/metrics), [Baseten benchmarks explainer](https://www.baseten.co/blog/understanding-performance-benchmarks-for-llm-inference/).

## Background — where the numbers come from

The ralph runner writes two kinds of logs:

1. **Per-step logs** — `<state>/logs/YYYYMMDD_HHMMSS_<step>.log` (one file per step invocation). Steps that run through **opencode** (`engine="opencode"`) stream opencode's JSON events, including `step_finish` blobs with full token usage.
2. **Master logs** — `<state>/logs/ralph_master_YYYYMMDD_HHMMSS.log` (one per runner process). These contain `COMPLETED (<bytes>B in <seconds>s)` lines per step and a subset of `step_finish` events.

**Important caveat:** Only opencode-backed steps emit token events. Claude Code–backed steps (`model="haiku"/"sonnet"/"opus"` without `engine="opencode"`) run via the Claude CLI and do **not** log token usage. Their token cost must be estimated separately (e.g. from the Anthropic console or by running an SDK wrapper that reports usage).

Typical engine mapping for riemann2-style pipelines:
- opencode (tokens logged): `finalize`, `fix`, `validate`, `critic`, `execute.lean`, `execute.research`
- Claude CLI (tokens not logged): `orient`, `plan`, default `execute`

## Arguments

$ARGUMENTS — optional path to the ralph state directory containing `logs/`. Defaults to `research/ralph` relative to cwd.

## Workflow

### Step 1: Locate logs

```bash
STATE_DIR="${1:-research/ralph}"
ls "$STATE_DIR/logs/" | head -5
ls "$STATE_DIR/logs/" | wc -l
```

Sanity-check that both per-step logs (timestamped filenames) and `ralph_master_*.log` files exist.

### Step 2: Parse tokens from per-step logs

Per-step logs contain every `step_finish` emitted by opencode during that step (including retries). The event format is:

```json
{"type":"step_finish","timestamp":<ms>,"sessionID":"...","part":{...,"tokens":{"total":N,"input":N,"output":N,"reasoning":N,"cache":{"write":N,"read":N}}}}
```

Run this script to aggregate by step name:

```python
import re, glob, os
from collections import defaultdict

STATE = os.environ.get("STATE_DIR", "research/ralph")

tok_pat = re.compile(
    r'"type":"step_finish"[^{]*"timestamp":(\d+).*?'
    r'"tokens":\{"total":(\d+),"input":(\d+),"output":(\d+),"reasoning":(\d+),'
    r'"cache":\{"write":(\d+),"read":(\d+)\}\}'
)

step_logs = glob.glob(f"{STATE}/logs/*_*.log")
# Filter out master logs
step_logs = [p for p in step_logs if "ralph_master_" not in p]

agg = defaultdict(lambda: dict(events=0, inp=0, out=0, cr=0, cw=0, reas=0, dur=0.0, n_logs=0))

for log in step_logs:
    base = os.path.basename(log)
    m = re.match(r'(\d{8})_(\d{6})_(\w+?)(_ratelimit\d+)?\.log', base)
    if not m:
        continue
    step = m.group(3)
    try:
        with open(log, errors="ignore") as f:
            data = f.read()
    except Exception:
        continue

    ts_min = ts_max = None
    for m2 in tok_pat.finditer(data):
        ts, _tot, inp, out, reas, cw, cr = map(int, m2.groups())
        a = agg[step]
        a["events"] += 1
        a["inp"] += inp; a["out"] += out; a["reas"] += reas
        a["cw"] += cw;  a["cr"] += cr
        ts_min = ts if ts_min is None else min(ts_min, ts)
        ts_max = ts if ts_max is None else max(ts_max, ts)

    if ts_min and ts_max and ts_max > ts_min:
        agg[step]["dur"] += (ts_max - ts_min) / 1000.0
        agg[step]["n_logs"] += 1

print(f"{'step':14s} {'logs':>5s} {'events':>7s} {'input':>14s} {'output':>12s} {'cache_r':>14s} {'dur(h)':>8s} {'in/s':>8s} {'out/s':>8s}")
T = dict(events=0, inp=0, out=0, cr=0, cw=0, dur=0.0)
for step, d in sorted(agg.items(), key=lambda x: -x[1]["inp"]):
    ins = d["inp"]/d["dur"] if d["dur"] else 0
    outs = d["out"]/d["dur"] if d["dur"] else 0
    print(f"{step:14s} {d['n_logs']:5d} {d['events']:7d} {d['inp']:>14,} {d['out']:>12,} {d['cr']:>14,} {d['dur']/3600:8.2f} {ins:8.1f} {outs:8.1f}")
    for k in ("events","inp","out","cr","cw","dur"):
        T[k] += d[k]

print()
if T["dur"]:
    print(f"TOTAL over {T['dur']/3600:.2f}h active opencode time, {T['events']} events:")
    print(f"  input   {T['inp']:>14,}   rate {T['inp']/T['dur']:.1f} tok/s")
    print(f"  output  {T['out']:>14,}   rate {T['out']/T['dur']:.1f} tok/s")
    print(f"  cache_r {T['cr']:>14,}   rate {T['cr']/T['dur']:.1f} tok/s")
```

### Step 3: Pair with COMPLETED durations from master logs

The duration above is the span between the first and last `step_finish` **inside a step**. To get the loop-wide wall clock (including Claude CLI steps that don't emit tokens), parse `COMPLETED` lines from master logs:

```python
import re, glob
completed_pat = re.compile(r'\[(\w+)\]\s+COMPLETED\s+\([\d,]+B\s+in\s+([\d.]+)s\)')
step_dur = {}
for log in glob.glob(f"{STATE}/logs/ralph_master_*.log"):
    with open(log, errors="ignore") as f:
        for m in completed_pat.finditer(f.read()):
            step_dur[m.group(1)] = step_dur.get(m.group(1), 0) + float(m.group(2))
for s, d in sorted(step_dur.items(), key=lambda x: -x[1]):
    print(f"  {s:12s} {d/3600:7.2f}h")
print(f"  TOTAL        {sum(step_dur.values())/3600:7.2f}h")
```

Divide opencode token totals by total step-wall-time (not just opencode time) to get a **loop-averaged** rate. Rate-while-active is higher than loop-averaged by the opencode-time fraction.

### Step 3.5: Per-event-gap rates (decode-rate proxy)

Agent throughput hides a critical fact: most gaps between `step_finish` events are tool execution, not generation. Compute per-event gap rates to see when the model is actually doing work:

```python
import re, statistics as st, sys

LOG = sys.argv[1] if len(sys.argv) > 1 else "research/ralph/logs/<step>.log"

pat = re.compile(
    r'"type":"step_finish"[^{]*"timestamp":(\d+).*?'
    r'"tokens":\{"total":\d+,"input":(\d+),"output":(\d+),"reasoning":(\d+),'
    r'"cache":\{"write":(\d+),"read":(\d+)\}\}'
)

events = []
with open(LOG, errors="ignore") as f:
    for m in pat.finditer(f.read()):
        ts, inp, out, reas, cw, cr = map(int, m.groups())
        events.append((ts, inp, out, reas, cw, cr))

print(f"events: {len(events)}, span: {(events[-1][0]-events[0][0])/1000:.1f}s")

gaps, in_rates, out_rates = [], [], []
for i in range(1, len(events)):
    dt = (events[i][0] - events[i-1][0]) / 1000
    if dt <= 0: continue
    gaps.append(dt)
    if events[i][1] > 0: in_rates.append(events[i][1] / dt)
    if events[i][2] > 0: out_rates.append(events[i][2] / dt)

print(f"gap     median {st.median(gaps):6.1f}s  mean {st.mean(gaps):6.1f}s  max {max(gaps):6.1f}s")
print(f"input   median {st.median(in_rates):6.0f}/s  max {max(in_rates):6.0f}/s")
print(f"output  median {st.median(out_rates):6.1f}/s  max {max(out_rates):6.1f}/s")

tin, tout = sum(e[1] for e in events), sum(e[2] for e in events)
span = (events[-1][0]-events[0][0])/1000
print(f"\nagent-TPS (sum/span):  in={tin/span:.0f}/s  out={tout/span:.2f}/s")
print(f"model-TPS proxy (max per-event rate is closer to true decode):")
print(f"  input  prefill upper bound ~{max(in_rates):.0f} tok/s")
print(f"  output decode upper bound  ~{max(out_rates):.1f} tok/s")
```

**Interpretation:**
- A **large `max gap`** (>100s) signals tool dominance — the bottleneck is `lake build`/Bash, not the model.
- **Median per-event input rate** ≈ provider prefill (sane comparison vs published numbers).
- **Max per-event output rate** is the closest proxy to raw decode TPS available without ITL instrumentation.
- If `max output rate` is ~10× the agent TPS, the loop is tool-bound, not model-bound. If it's only 1–2×, the model itself is the bottleneck.

To recover true ITL, opencode logs per-tool timestamps in `parts[].time.{start,end}` — subtract those from each gap before dividing. We don't currently parse this, but the [opencode-tokenscope](https://github.com/ramtinJ95/opencode-tokenscope) project has reference code.

### Step 4: Report

Emit four numbers:

1. **Agent throughput while an opencode step is active** — token total ÷ opencode active duration. *Use for capacity / cost planning.*
2. **Loop-averaged agent throughput** — token total ÷ total step-wall-time across all steps. *Use for "is my quota enough".*
3. **Per-event prefill / decode bounds** — median per-event input rate, max per-event output rate. *Use to compare against provider benchmarks.*
4. **Per-step breakdown** — useful for spotting which step dominates spend.

Flag caveats explicitly:
- Claude-CLI steps contribute 0 tokens to these numbers (Claude CLI doesn't log usage). Real loop usage is higher.
- Cache tokens are provider-specific: gpt-5.2 reports `cache_read` heavily (often 5–10× input, ≈80% latency reduction per OpenAI docs); kimi/nvidia runs report 0.
- Retries (`_ratelimit<N>`, `lean_retry_<N>` filenames) count as separate logs — keep them grouped or split depending on the question.
- **Agent TPS ≪ model TPS in tool-heavy loops.** A finalize step that shows 5 tok/s output is almost certainly bottlenecked on tool calls, not model decode.

## Provider reference numbers (April 2026, for sanity-checking)

| provider / model | published output TPS | prefill | cache | notes |
|---|---|---|---|---|
| **NVIDIA NIM Kimi K2.5** (`build.nvidia.com`) | not published | not published | none | shared endpoint, 40 RPM/key default, slower than self-host |
| Kimi K2.5 (Baseten B200, tuned) | ~340 tok/s | — | — | upper bound; NIM shared is much less |
| Kimi K2.5 (Baseten standard) | ~140 tok/s @ TTFT 300ms | — | — | typical tuned third-party |
| **OpenAI gpt-5.2** (Artificial Analysis P50, xhigh) | ~70 tok/s | — | 80% latency reduction | TTFT 137s (reasoning tokens) |
| OpenAI gpt-5.2 (llm-benchmarks avg) | ~31 tok/s | — | — | high variance (CV ~98%) |

**Plausibility check:** if your computed *agent* output TPS is much below the published *decode* TPS, that's expected for a tool-heavy loop. If your *per-event max* output TPS is also far below published, you may have rate-limit throttling, a noisy shared endpoint, or a real provider regression — investigate.

Sources for the table: [NIM model card](https://build.nvidia.com/moonshotai/kimi-k2.5/modelcard), [NIM API ref](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k2-5), [Baseten Kimi K2.5](https://www.baseten.co/blog/how-we-built-the-fastest-kimi-k2-5-on-artificial-analysis/), [Artificial Analysis gpt-5.2](https://artificialanalysis.ai/models/gpt-5-2/providers), [llm-benchmarks gpt-5.2](https://llm-benchmarks.com/models/openai/gpt52), [OpenAI prompt caching](https://openai.com/index/api-prompt-caching/).

## Expected shape of output

Something like:

```
step           logs   events          input       output        cache_r   dur(h)     in/s    out/s
finalize        138     1823    138,336,887    1,627,984              0    23.28   1650.7     19.4
execute          13      450     32,458,508      195,339              0     4.98   1811.3     10.9
validate         25      378      2,140,940       84,373     19,207,808     1.27    468.6     18.5
...

TOTAL over 32.72h active opencode time, 3329 events:
  input   190,271,961   rate 1615.5 tok/s
  output    2,085,495   rate    17.7 tok/s
  cache_r  31,308,928   rate   266.1 tok/s
```

## Gotchas

- **Step logs are huge.** Don't `cat` them; let the script read them directly. A single finalize log can be 1–3 MB.
- **Engine detection.** A step is opencode-backed if its log's first line contains `[execwrap] Wrapping: /.../opencode run --model ...`. Use this to classify unfamiliar steps if the ralph config isn't obvious.
- **Master logs under-report events.** They only capture a tail of `step_finish` events per cycle (typically 3–4), so compute token totals from per-step logs, not master logs.
- **Timestamp units.** `step_finish.timestamp` is Unix **milliseconds**; `COMPLETED (... in Ns)` is seconds. Don't mix.
- **Empty logs.** `orient`/`plan`/default `execute` logs often contain only the final text output from Claude CLI — no JSON events. Expect zero token data from those.
