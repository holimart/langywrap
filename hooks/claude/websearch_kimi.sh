#!/bin/bash
# websearch_kimi.sh
# PreToolUse hook: intercepts WebSearch, calls Kimi K2.5 via NVIDIA NIM.
# Blueprint — copy to ~/.claude/hooks/ for global use, or .claude/hooks/ for per-project.

INPUT=$(cat)

# Extract query from Claude Code's tool_input JSON
QUERY=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('query', ''))
except:
    print('')
" 2>/dev/null)

if [ -z "$QUERY" ]; then
    exit 0  # no query — pass through
fi

# Read NVIDIA API key from opencode auth store
NVIDIA_KEY=$(python3 -c "
import json
try:
    d = json.load(open('/home/martin/.local/share/opencode/auth.json'))
    print(d['nvidia']['key'])
except:
    print('')
" 2>/dev/null)

if [ -z "$NVIDIA_KEY" ]; then
    exit 0  # no key — pass through to native WebSearch
fi

# Detect query intent: detailed vs compact
# Detailed triggers: explain, how, why, what is, compare, overview, history, analysis, guide
STYLE=$(python3 -c "
import sys, re
query = sys.argv[1].lower()
detail_patterns = [
    r'\b(explain|how does|how do|how to|why|what is|what are|compare|vs\.?|versus|overview|history|analysis|guide|tutorial|deep.?dive|comprehensive|detailed|in.?depth)\b'
]
for p in detail_patterns:
    if re.search(p, query):
        print('detailed')
        break
else:
    print('compact')
" "$QUERY")

if [ "$STYLE" = "detailed" ]; then
    SYSTEM_PROMPT="You are a web search assistant. Answer the query thoroughly: include key facts, relevant URLs, dates, sources. Use bullet points or short paragraphs. Max 400 words."
    MAX_TOKENS=1200
    MODEL="moonshotai/kimi-k2.5"
else
    SYSTEM_PROMPT="You are a web search assistant. Give a compact answer: 3-6 bullet points, max 120 words. Key facts only. No preamble."
    MAX_TOKENS=400
    MODEL="moonshotai/kimi-k2-instruct"
fi

# Build request payload
PAYLOAD=$(python3 -c "
import json, sys
query, system_prompt, max_tokens, model = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
payload = {
    'model': model,
    'messages': [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user',   'content': query}
    ],
    'max_tokens': max_tokens
}
print(json.dumps(payload))
" "$QUERY" "$SYSTEM_PROMPT" "$MAX_TOKENS" "$MODEL")

# Call NVIDIA NIM — on failure/timeout, pass through to native WebSearch
RESPONSE=$(curl -s --max-time 90 \
    -X POST https://integrate.api.nvidia.com/v1/chat/completions \
    -H "Authorization: Bearer $NVIDIA_KEY" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" 2>/dev/null) || exit 0

# Extract content (kimi-k2.5 is a thinking model: prefer content, fallback to reasoning)
CONTENT=$(echo "$RESPONSE" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    msg = d['choices'][0]['message']
    content = (msg.get('content') or '').strip()
    reasoning = (msg.get('reasoning') or '').strip()
    if content:
        print(content)
    elif reasoning:
        print('[Kimi reasoning]\n' + reasoning[:1500])
    else:
        print('')
except:
    print('')
" 2>/dev/null)

if [ -z "$CONTENT" ]; then
    exit 0  # API error — pass through to native WebSearch
fi

# Output hook response: deny WebSearch, inject Kimi result as context
python3 -c "
import json, sys
content, query, style = sys.argv[1], sys.argv[2], sys.argv[3]
result = {
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': 'Search handled by Kimi K2.5 (NVIDIA NIM)',
        'additionalContext': '[WebSearch via Kimi K2.5 | ' + style + ']\nQuery: ' + query + '\n\n' + content
    }
}
print(json.dumps(result))
" "$CONTENT" "$QUERY" "$STYLE"
