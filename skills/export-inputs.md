---
description: Export all user inputs from conversation history to a markdown file for backup
allowed-tools: Read, Bash, Write
---

# Export User Inputs

Extract all user messages from Claude Code conversation history and save to a markdown file for backup purposes.

## Purpose

- Preserve user inputs before clearing Claude conversation files
- Create a searchable archive of all requests, ideas, and decisions
- Enable knowledge recovery after conversation cleanup

## Execution

Run this single command to extract and save all user inputs:

```bash
./uv run python -c "
import json
import os
import re
from datetime import datetime
from pathlib import Path

# Dynamic history dir based on cwd
cwd = os.getcwd()
project_slug = cwd.replace('/', '-').lstrip('-')
HISTORY_DIR = Path(os.path.expanduser(f'~/.claude/projects/-{project_slug}'))
OUTPUT_DIR = Path('notes')
OUTPUT_DIR.mkdir(exist_ok=True)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
output_file = OUTPUT_DIR / f'user_inputs_backup_{timestamp}.md'

# Patterns to skip
SKIP_PATTERNS = [
    r'^\[Request interrupted',          # Interrupted requests
    r'^This session is being continued', # Context summaries (keep first 500 chars)
]

def is_skip_message(content):
    if not content or len(content.strip()) < 5:
        return True
    stripped = content.strip()
    # Skip system/command tags
    if stripped.startswith('<'):
        return True
    # Skip tool results
    if stripped.startswith('{') and 'tool_use_id' in stripped:
        return True
    if stripped.startswith(\"{'tool_use_id\"):
        return True
    # Skip short slash commands
    if stripped.startswith('/') and len(stripped) < 50:
        return True
    # Skip file listings
    if re.match(r'^[a-z_]+/.*:', stripped):
        return True
    if re.match(r'^[\s\d]+→', stripped):
        return True
    # Skip interrupted requests
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, stripped):
            return True
    return False

def clean_content(content):
    content = re.sub(r'<command-name>.*?</command-name>', '', content)
    content = re.sub(r'<command-message>.*?</command-message>', '', content)
    content = re.sub(r'<command-args>.*?</command-args>', '', content)
    content = re.sub(r'<local-command-.*?>.*?</local-command-.*?>', '', content, flags=re.DOTALL)
    content = re.sub(r'<system-reminder>.*?</system-reminder>', '', content, flags=re.DOTALL)
    return content.strip()

def truncate_context_summary(content, max_len=800):
    \"\"\"Truncate long context summaries but keep actual user messages.\"\"\"
    if content.startswith('This session is being continued'):
        if len(content) > max_len:
            return content[:max_len] + '\\n\\n*[...truncated context summary...]*'
    return content

if not HISTORY_DIR.exists():
    print(f'History directory not found: {HISTORY_DIR}')
    exit(1)

jsonl_files = list(HISTORY_DIR.glob('*.jsonl'))
print(f'Found {len(jsonl_files)} conversation files')

# Extract all messages with timestamps
all_messages = []
for jf in jsonl_files:
    with open(jf, 'r', errors='ignore') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if data.get('type') == 'user' and not data.get('isMeta'):
                    content = data.get('message', {}).get('content', '')
                    ts = data.get('timestamp', '')

                    # Skip tool result lists
                    if isinstance(content, list):
                        is_tool_result = any(
                            isinstance(item, dict) and item.get('type') == 'tool_result'
                            for item in content
                        )
                        if is_tool_result:
                            continue
                        content = ' '.join(
                            item.get('text', '') if isinstance(item, dict) else str(item)
                            for item in content
                            if not (isinstance(item, dict) and item.get('type') == 'tool_result')
                        )

                    cleaned = clean_content(content)
                    if cleaned and not is_skip_message(cleaned):
                        cleaned = truncate_context_summary(cleaned)
                        all_messages.append({
                            'session': jf.stem,
                            'content': cleaned,
                            'timestamp': ts,
                        })
            except:
                pass

print(f'Extracted {len(all_messages)} user messages')

# Group by session and sort by first message timestamp
sessions = {}
session_first_ts = {}
for msg in all_messages:
    s = msg['session']
    if s not in sessions:
        sessions[s] = []
        session_first_ts[s] = msg['timestamp']
    sessions[s].append(msg)

# Sort sessions by first timestamp (chronological order)
sorted_sessions = sorted(sessions.keys(), key=lambda s: session_first_ts.get(s, ''))

# Get date range
all_timestamps = [m['timestamp'] for m in all_messages if m['timestamp']]
if all_timestamps:
    first_date = min(all_timestamps)[:10]
    last_date = max(all_timestamps)[:10]
    date_range = f'{first_date} to {last_date}'
else:
    date_range = 'unknown'

# Write output
with open(output_file, 'w') as f:
    f.write('# User Inputs Backup\\n\\n')
    f.write(f'**Exported:** {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")}\\n')
    f.write(f'**Project:** {Path(cwd).name}\\n')
    f.write(f'**Date Range:** {date_range}\\n')
    f.write(f'**Total:** {len(all_messages)} messages in {len(sessions)} sessions\\n\\n')
    f.write('---\\n\\n')

    # Table of contents with session dates
    f.write('## Sessions (chronological)\\n\\n')
    for i, session in enumerate(sorted_sessions, 1):
        msgs = sessions[session]
        first_ts = session_first_ts.get(session, '')[:10] or '?'
        f.write(f'{i}. **{first_ts}** - Session {session[:8]}... ({len(msgs)} messages)\\n')
    f.write('\\n---\\n\\n')

    # Messages by session (chronological order)
    for session in sorted_sessions:
        msgs = sessions[session]
        first_ts = session_first_ts.get(session, '')[:10] or 'unknown date'
        f.write(f'## {first_ts} - Session {session[:8]}...\\n\\n')

        for i, m in enumerate(msgs, 1):
            ts_str = ''
            if m['timestamp']:
                try:
                    dt = datetime.fromisoformat(m['timestamp'].replace('Z', '+00:00'))
                    ts_str = f' *({dt.strftime(\"%H:%M\")})*'
                except:
                    pass
            f.write(f'### {i}.{ts_str}\\n\\n')
            f.write(m['content'])
            f.write('\\n\\n---\\n\\n')

print(f'\\nOutput: {output_file}')
print(f'Size: {output_file.stat().st_size / 1024:.1f} KB')
"
```

After running, verify with:

```bash
OUTPUT_FILE=\$(ls -t notes/user_inputs_backup_*.md 2>/dev/null | head -1)
echo "=== Backup Summary ==="
head -20 "\$OUTPUT_FILE"
```

## Arguments

- (no args) - Full export with all user inputs
- `recent` - Only export from the last 5 sessions
- `search {term}` - Export only messages containing the search term

## Output Format

```markdown
# User Inputs Backup

**Exported:** 2025-01-31 10:30:00
**Project:** [your-project]
**Date Range:** 2025-01-15 to 2025-01-31
**Total:** 317 messages in 18 sessions

---

## Sessions (chronological)

1. **2025-01-15** - Session 36ce5805... (12 messages)
2. **2025-01-18** - Session 4dd6065c... (8 messages)
...

---

## 2025-01-15 - Session 36ce5805...

### 1. *(09:30)*

Your user message here...

---
```

## Key Features

- **Chronological order**: Sessions sorted by date, not UUID
- **Tool result filtering**: Skips tool outputs that get echoed as user messages
- **Context summary truncation**: Long "This session is being continued..." summaries are truncated
- **Date range header**: Shows the time span covered by the backup
- **Dynamic project detection**: Works for any project directory
