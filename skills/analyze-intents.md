---
description: Analyze user intent patterns from conversation history and suggest acceptance criteria
allowed-tools: Read, Bash, Grep, Glob, Write, Edit, AskUserQuestion
---

# Intent Analysis Workflow

Analyze conversation history to discover repeated user intents and suggest new acceptance criteria.

## Overview

This skill:
1. Extracts user messages from Claude Code conversation history (JSONL files)
2. Identifies patterns and repeated intents
3. Compares with existing acceptance criteria in DESIGN_PRINCIPLES.md
4. Suggests new acceptance criteria for common uncovered patterns

## Execution Steps

### Step 1: Locate Conversation History

Find the project's conversation history directory:

```bash
# Project directory is derived from cwd path
# The project directory path is converted to a slug format
# Example: /home/user/myproject becomes ~/.claude/projects/-home-user-myproject/

PROJECT_DIR=$(pwd | sed 's|/|-|g' | sed 's|^-||')
HISTORY_DIR="$HOME/.claude/projects/-${PROJECT_DIR}"

# List available JSONL files
ls -la "$HISTORY_DIR"/*.jsonl 2>/dev/null | wc -l
```

### Step 2: Extract User Messages

Extract user messages efficiently from JSONL files.

**Important:** JSONL files can be 50-100MB each (417MB total). User messages often contain
large code blocks. We use a streaming approach that:
1. Uses `grep` to extract only user message lines (not full file reads)
2. Extracts only the first 300 chars of content (enough for intent analysis)
3. Filters out system messages and slash commands

```bash
# Efficient extraction - only reads matching lines, truncates content early
# Set this to your project's history directory (use the command from Step 1)
HISTORY_DIR="$HOME/.claude/projects/-YOUR-PROJECT-SLUG"

# Use grep to get user lines, then extract just the content start with sed+cut
# This avoids loading full message content into memory
grep -h '"type":"user"' "$HISTORY_DIR"/*.jsonl 2>/dev/null | \
  sed 's/.*"content":"\([^"]*\).*/\1/' | \
  cut -c1-300 | \
  grep -v '^<' | \
  grep -v '^/' | \
  sort | uniq -c | sort -rn | head -100
```

**Recommended: Python streaming with noise filtering:**

```bash
# Set this to your project's history directory (use the command from Step 1)
HISTORY_DIR="$HOME/.claude/projects/-YOUR-PROJECT-SLUG"

# Stream-process with noise filtering to get actual user intents
grep -h '"type":"user"' "$HISTORY_DIR"/*.jsonl 2>/dev/null | \
  ./uv run python -c "
import sys
import re

# Skip patterns that indicate tool output echoed in messages, not user intent
SKIP_PATTERNS = [
    r'^[\s\d]+→',            # Line numbers from file reads
    r'^total \d+',           # ls output
    r'^drw|^-rw',            # File permissions
    r'^Found \d+ files',     # Search results
    r'^Todos have been',     # System confirmations
    r'^The file .* has been', # Edit confirmations
    r'^File created',        # Write confirmations
    r'^Exception|Error',     # Errors
    r'^INFO:|^DEBUG:',       # Log output
    r'^This session is being', # Context summaries
    r'^\./uv run',           # Command echoes
    r'^#!/',                 # Shebang lines
    r'^Web search results',  # Search result headers
    r'^All checks passed',   # Validation output
    r'^E\d{3} ',             # Lint errors
    r'^plugins:',            # Pytest output
    r'^error:',              # Error messages
]

for line in sys.stdin:
    # Early truncation - intent is in first ~200 chars
    truncated = line[:2000]
    try:
        idx = truncated.find('\"content\":\"')
        if idx == -1:
            continue
        start = idx + 11
        end = min(start + 300, len(truncated))
        content = truncated[start:end].split('\"')[0]

        # Skip system/command messages
        if content.startswith('<') or content.startswith('/'):
            continue
        if len(content) < 15:
            continue

        # Skip tool output noise
        skip = False
        for pattern in SKIP_PATTERNS:
            if re.match(pattern, content):
                skip = True
                break
        if skip:
            continue

        # Clean and output
        content = content.replace('\\\\n', ' ').replace('\\\\t', ' ').strip()
        if content:
            print(content[:200])
    except:
        pass
"
```

**Performance comparison:**

| Approach | Memory | Time | Notes |
|----------|--------|------|-------|
| Full JSON parse | ~300MB | ~30s | Loads all content |
| Sed+cut | ~10MB | ~2s | Fast but loses escapes |
| Python truncate | ~20MB | ~3s | Best accuracy/perf balance |

### Step 3: Categorize Intents

Analyze extracted messages and categorize by intent type:

**Intent Categories:**

| Category | Pattern Examples | Description |
|----------|-----------------|-------------|
| **Implementation** | "add", "create", "implement", "build" | Requests to build new features |
| **Fix/Debug** | "fix", "bug", "error", "broken", "not working" | Requests to fix issues |
| **Refactor** | "refactor", "clean up", "improve", "optimize" | Code improvement requests |
| **Documentation** | "document", "readme", "explain", "comment" | Documentation requests |
| **Testing** | "test", "coverage", "verify", "check" | Testing-related requests |
| **Data/Query** | "fetch", "scrape", "load", "query", "data" | Data operations |
| **Config** | "configure", "setup", "settings", "env" | Configuration requests |
| **Review** | "review", "check", "validate", "audit" | Review/validation requests |

Use this Python analysis:

```python
import re
from collections import defaultdict, Counter

# Intent patterns (regex)
INTENT_PATTERNS = {
    'implementation': r'\b(add|create|implement|build|make|new|write)\b',
    'fix_debug': r'\b(fix|bug|error|broken|fail|crash|issue|problem|not working)\b',
    'refactor': r'\b(refactor|clean|improve|optimize|simplify|reorganize)\b',
    'documentation': r'\b(document|readme|explain|comment|describe|docs)\b',
    'testing': r'\b(test|coverage|verify|assert|mock|fixture)\b',
    'data_operations': r'\b(fetch|scrape|load|query|data|process|transform|parse)\b',
    'configuration': r'\b(configure|setup|settings|env|config|parameter)\b',
    'review_validate': r'\b(review|check|validate|audit|analyze|inspect)\b',
    'research': r'\b(find|search|look|where|how|what|which)\b',
}

def categorize_intent(message):
    """Categorize a message by its primary intent."""
    message_lower = message.lower()
    matches = {}
    for category, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, message_lower):
            matches[category] = len(re.findall(pattern, message_lower))
    return matches

def extract_action_objects(message):
    """Extract action-object pairs from message."""
    # Common patterns: "add X", "fix Y", "create Z"
    patterns = [
        r'\b(add|create|implement|fix|update|remove|delete)\s+(?:a\s+)?(?:the\s+)?(\w+(?:\s+\w+)?)',
        r'\b(scraper|loader|test|feature|function|class|method)\b',
    ]
    objects = []
    for pattern in patterns:
        matches = re.findall(pattern, message.lower())
        objects.extend(matches)
    return objects
```

### Step 4: Identify Repeated Patterns

Count frequency of intent patterns:

```python
from collections import Counter

def analyze_patterns(messages):
    """Find repeated patterns across messages."""

    # Count intent categories
    intent_counts = Counter()
    action_object_counts = Counter()
    keyword_counts = Counter()

    for msg in messages:
        # Count intents
        intents = categorize_intent(msg)
        for intent, count in intents.items():
            intent_counts[intent] += count

        # Count action-object pairs
        pairs = extract_action_objects(msg)
        for pair in pairs:
            action_object_counts[pair] += 1

        # Count significant keywords
        words = re.findall(r'\b[a-z]{4,}\b', msg.lower())
        for word in words:
            if word not in STOPWORDS:
                keyword_counts[word] += 1

    return {
        'intents': intent_counts.most_common(10),
        'actions': action_object_counts.most_common(20),
        'keywords': keyword_counts.most_common(30),
    }

# Example output:
# intents: [('implementation', 45), ('data_operations', 38), ('fix_debug', 22)]
# actions: [('add scraper', 12), ('fix test', 8), ('create loader', 7)]
# keywords: [('scraper', 50), ('loader', 35), ('test', 30), ('data', 28)]
```

### Step 5: Load Existing Acceptance Criteria

Read DESIGN_PRINCIPLES.md to get existing acceptance criteria:

```python
def extract_acceptance_criteria(filepath):
    """Extract all EARS acceptance criteria from design principles."""
    criteria = []
    with open(filepath) as f:
        content = f.read()

    # Find all WHEN...SHALL patterns
    pattern = r'\d+\.\s+WHEN\s+(.+?)\s+THE SYSTEM SHALL\s+(.+?)(?=\n\d+\.|$)'
    matches = re.findall(pattern, content, re.DOTALL)

    for condition, behavior in matches:
        criteria.append({
            'condition': condition.strip(),
            'behavior': behavior.strip(),
            'full': f"WHEN {condition.strip()} THE SYSTEM SHALL {behavior.strip()}"
        })

    return criteria
```

### Step 6: Gap Analysis

Compare user intents with existing acceptance criteria:

```python
def find_gaps(user_patterns, existing_criteria):
    """Find user intents not covered by existing acceptance criteria."""

    gaps = []

    # Extract keywords from criteria
    criteria_keywords = set()
    for criterion in existing_criteria:
        words = re.findall(r'\b[a-z]{4,}\b', criterion['full'].lower())
        criteria_keywords.update(words)

    # Find frequently requested actions not in criteria
    for action, count in user_patterns['actions']:
        if count >= 3:  # Threshold for "repeated"
            action_words = set(action.lower().split())
            if not action_words & criteria_keywords:
                gaps.append({
                    'action': action,
                    'frequency': count,
                    'type': 'uncovered_action',
                    'suggestion': f"Consider adding criteria for: {action}"
                })

    # Find frequently mentioned concepts not in criteria
    for keyword, count in user_patterns['keywords']:
        if count >= 5 and keyword not in criteria_keywords:
            gaps.append({
                'keyword': keyword,
                'frequency': count,
                'type': 'uncovered_concept',
                'suggestion': f"Frequent concept '{keyword}' may need acceptance criteria"
            })

    return gaps
```

### Step 7: Generate Suggested Criteria

For identified gaps, suggest EARS acceptance criteria:

```python
def suggest_criteria(gaps):
    """Generate suggested acceptance criteria for gaps."""

    suggestions = []

    for gap in gaps:
        if gap['type'] == 'uncovered_action':
            action = gap['action']
            # Generate context-aware suggestion
            if 'scraper' in action:
                suggestions.append({
                    'gap': gap,
                    'suggested_criteria': [
                        f"WHEN a new {action} is requested THE SYSTEM SHALL follow scraper design patterns in Section 2",
                        f"WHEN {action} is implemented THE SYSTEM SHALL include OUTPUT_SCHEMA and SCRAPE_SCHEDULE",
                    ]
                })
            elif 'test' in action:
                suggestions.append({
                    'gap': gap,
                    'suggested_criteria': [
                        f"WHEN implementing {action} THE SYSTEM SHALL cover happy path and edge cases",
                        f"WHEN {action} fails THE SYSTEM SHALL provide clear error messages",
                    ]
                })
            else:
                suggestions.append({
                    'gap': gap,
                    'suggested_criteria': [
                        f"WHEN user requests to {action} THE SYSTEM SHALL validate inputs first",
                        f"WHEN {action} completes THE SYSTEM SHALL verify success criteria",
                    ]
                })

    return suggestions
```

### Step 8: Present Results

Format and present the analysis:

```markdown
# Intent Analysis Report

## Summary

- **Total conversations analyzed:** {count}
- **User messages extracted:** {count}
- **Unique intents identified:** {count}

## Top Intent Categories

| Category | Frequency | Example Messages |
|----------|-----------|------------------|
| {category} | {count} | "{example}" |

## Repeated Action Patterns

| Action | Frequency | Currently Covered? |
|--------|-----------|-------------------|
| {action} | {count} | {yes/no} |

## Gaps Identified

### Uncovered Actions

{list of actions not in acceptance criteria}

### Uncovered Concepts

{list of concepts frequently mentioned but not in criteria}

## Suggested Acceptance Criteria

### For: {gap description}

**Suggested Addition to DESIGN_PRINCIPLES.md:**

```markdown
### {Section}.{Subsection} {New Principle Name}

**Principle**: {Derived from user intents}

**Acceptance Criteria**:

1. WHEN {condition} THE SYSTEM SHALL {behavior}
2. WHEN {condition} THE SYSTEM SHALL {behavior}
```

## Recommendations

1. **High Priority:** Add criteria for {most frequent uncovered action}
2. **Medium Priority:** Document process for {common workflow}
3. **Consider:** Creating new skill for {repeated complex task}
```

### Step 9: Offer Updates

If gaps are significant, offer to update DESIGN_PRINCIPLES.md:

```
Based on the analysis, I found {N} repeated user intents not covered by acceptance criteria.

Would you like me to:
1. Add these as new acceptance criteria to DESIGN_PRINCIPLES.md
2. Create a new section for {category}
3. Just show the report without changes
```

Use AskUserQuestion to get user preference.

## Arguments

- (no args) - Full analysis with suggestions
- `report` - Generate report only, no suggestions
- `update` - Analyze and update DESIGN_PRINCIPLES.md with suggestions
- `category {name}` - Focus on specific intent category

## Example Output

```
/analyze-intents

Analyzing 47 conversation sessions...
Extracted 312 user messages.

Top Patterns:
1. "add scraper" - 15 occurrences (COVERED by Section 2.1)
2. "fix test" - 12 occurrences (COVERED by Section 9.4)
3. "run validation" - 10 occurrences (PARTIALLY covered)
4. "check data quality" - 8 occurrences (COVERED by Section 7)
5. "update documentation" - 7 occurrences (COVERED by Section 9.3)
6. "incremental processing" - 6 occurrences (NOT COVERED)
7. "parallel execution" - 5 occurrences (NOT COVERED)

Gaps Found:
- "incremental processing" mentioned 6 times, no explicit criteria
- "parallel execution" mentioned 5 times, only implicit in rate limiting

Suggested New Criteria:

### 4.5 Incremental Processing

**Principle**: Support incremental updates for faster daily processing.

**Acceptance Criteria**:

1. WHEN incremental mode is enabled THE SYSTEM SHALL only process files newer than last run
2. WHEN determining cutoff time THE SYSTEM SHALL read file_timestamp from existing output
3. WHEN merging incremental results THE SYSTEM SHALL deduplicate with existing data
4. WHEN no existing output exists THE SYSTEM SHALL fall back to full rebuild

Would you like me to add this to DESIGN_PRINCIPLES.md? [Yes/No/Modify]
```
