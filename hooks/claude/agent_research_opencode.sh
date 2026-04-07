#!/bin/bash
# agent_research_opencode.sh
# PreToolUse hook: intercepts Agent tool calls with research/search intent,
# runs them via opencode (kimi-k2.5 / NVIDIA NIM) instead of burning Sonnet tokens.
# Blueprint — copy to ~/.claude/hooks/ for global use, or .claude/hooks/ for per-project.
#
# Triggers on Agent calls whose prompt contains research signals:
#   search, find, research, look up, web, browse, fetch, crawl, scrape,
#   gather info, investigate, discover, explore, survey, scan, market research, etc.
#
# Non-research agents (code, write, edit, implement) pass through to Claude as normal.

INPUT=$(cat)

# Extract the agent prompt from tool_input
PROMPT=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', {})
    # Agent tool uses 'prompt' field
    print(ti.get('prompt', ti.get('description', ti.get('task', ''))))
except:
    print('')
" 2>/dev/null)

if [ -z "$PROMPT" ]; then
    exit 0  # no prompt — pass through
fi

# Detect research intent
IS_RESEARCH=$(python3 -c "
import sys, re
prompt = sys.argv[1].lower()
research_patterns = [
    r'\b(search|web.?search|web.?fetch|browse|crawl|scrape|spider)\b',
    r'\b(research|investigate|survey|scan|discover|explore|look.?up)\b',
    r'\b(find|gather|collect).{0,30}(info|data|sources?|articles?|links?|urls?|pages?)\b',
    r'\b(market.?research|competitive.?intel|competitor.?anal|landscape.?anal)\b',
    r'\b(fetch.{0,20}(url|page|site|website|domain))\b',
    r'\b(grep|find.{0,20}files?|scan.{0,20}(code|repo|codebase))\b',
]
for p in research_patterns:
    if re.search(p, prompt):
        print('yes')
        break
else:
    print('no')
" "$PROMPT")

if [ "$IS_RESEARCH" != "yes" ]; then
    exit 0  # not research — pass through to Claude
fi

# Get NVIDIA API key from opencode auth store
NVIDIA_KEY=$(python3 -c "
import json
try:
    d = json.load(open('/home/martin/.local/share/opencode/auth.json'))
    print(d['nvidia']['key'])
except:
    print('')
" 2>/dev/null)

if [ -z "$NVIDIA_KEY" ]; then
    exit 0  # no key — pass through
fi

# Use a per-call isolated data dir — avoids SQLite DB locking when parallel opencode sessions run
SCRATCH_DIR=$(mktemp -d /tmp/opencode_hook_XXXXXX)
trap "rm -rf '$SCRATCH_DIR'" EXIT

# Write prompt to temp file (avoids ARG_MAX, matches ralph_loop pattern)
PROMPT_FILE=$(mktemp /tmp/opencode_agent_XXXXXX.txt)
echo "$PROMPT" > "$PROMPT_FILE"
OUTPUT_FILE=$(mktemp /tmp/opencode_output_XXXXXX.txt)

# Run opencode with kimi-k2.5 (same pattern as ralph_loop.sh)
# SHELL=/bin/bash is critical — without it opencode hangs (needs non-null SHELL to spawn subprocesses)
timeout 120 env \
    NVIDIA_API_KEY="$NVIDIA_KEY" \
    SHELL=/bin/bash \
    __EXECWRAP_ACTIVE=1 \
    XDG_DATA_HOME="$SCRATCH_DIR" \
    ~/.opencode/bin/opencode run \
    --model nvidia/moonshotai/kimi-k2.5 \
    --format json \
    < "$PROMPT_FILE" > "$OUTPUT_FILE" 2>/dev/null
EXIT_CODE=$?

rm -f "$PROMPT_FILE"

if [ "$EXIT_CODE" -ne 0 ] || [ ! -s "$OUTPUT_FILE" ]; then
    rm -f "$OUTPUT_FILE"
    exit 0  # failed — pass through to Claude
fi

# Extract the final assistant text from opencode's JSON event stream
RESULT=$(python3 -c "
import json, sys

output_file = sys.argv[1]
text_parts = []
last_tool_output = ''

with open(output_file) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except:
            continue

        etype = event.get('type', '')
        part = event.get('part', {})

        if etype == 'tool_use':
            state = part.get('state', {})
            if state.get('status') == 'completed':
                output = state.get('output', '')
                if output:
                    last_tool_output = output[:3000]

        elif etype == 'text':
            text = part.get('text', '')
            if text:
                text_parts.append(text)

final_text = ''.join(text_parts).strip()
if final_text:
    print(final_text)
elif last_tool_output:
    print('[Research results from tools]\n' + last_tool_output)
else:
    print('')
" "$OUTPUT_FILE" 2>/dev/null)

rm -f "$OUTPUT_FILE"

if [ -z "$RESULT" ]; then
    exit 0  # no usable output — pass through
fi

# Return: deny the Agent spawn, inject opencode result as context
python3 -c "
import json, sys
result = sys.argv[1]
output = {
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': 'Research agent handled by Kimi K2.5 via opencode (NVIDIA NIM)',
        'additionalContext': '[Research Agent via Kimi K2.5 / opencode]\n\n' + result
    }
}
print(json.dumps(output))
" "$RESULT"
