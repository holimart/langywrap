---
description: Spec-driven development with EARS acceptance criteria (Kiro-style workflow)
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(just), TodoWrite, AskUserQuestion
---

# Spec-Driven Development Workflow

Implement features using specification-driven development with EARS acceptance criteria.
This workflow mirrors Kiro's approach: requirements → design → tasks → implementation.

## Overview

This skill transforms a natural language feature request into:
1. **requirements.md** - User stories with EARS acceptance criteria
2. **design.md** - Technical architecture and data flow
3. **tasks.md** - Implementation checklist linked to requirements

The specs become the source of truth, preventing context drift and scope creep.

## Workflow

### Phase 1: Requirements Generation

When the user provides a feature request:

1. **Parse the intent** - Identify the core functionality requested
2. **Generate user stories** - Break into discrete user stories (As a... I want... So that...)
3. **Write EARS acceptance criteria** - For each story, write testable criteria

**EARS Notation Format:**
```
WHEN [condition/event] THE SYSTEM SHALL [expected behavior]
```

**Example transformation:**
```
User request: "Add a review system for products"

→ Generates:
Requirement 1: View product reviews
User Story: As a customer, I want to view reviews for products, so that I can make informed purchase decisions.

Acceptance Criteria:
1. WHEN a user views a product page THE SYSTEM SHALL display all reviews for that product
2. WHEN reviews exist THE SYSTEM SHALL show average rating, review count, and individual reviews
3. WHEN no reviews exist THE SYSTEM SHALL display "No reviews yet" message
4. WHEN displaying reviews THE SYSTEM SHALL show reviewer name, rating, date, and comment
```

### Phase 2: Technical Design

After requirements are approved:

1. **Analyze codebase** - Read relevant existing code to understand patterns
2. **Design components** - Identify new/modified files, classes, functions
3. **Define data models** - Schema changes, new types, interfaces
4. **Document data flow** - How data moves through the system
5. **Consider edge cases** - Error handling, validation, security

### Phase 3: Task Generation

Create implementation tasks:

1. **Break into atomic tasks** - Each task should be completable independently
2. **Sequence by dependencies** - Order tasks so prerequisites come first
3. **Link to requirements** - Each task references which acceptance criteria it satisfies
4. **Include verification** - Each task has a way to verify completion

**Task format:**
```markdown
- [ ] 1. Create database schema for reviews
    - Add reviews table with foreign keys
    - Add indexes for product_id and user_id
    - _Requirements: 1.1, 1.4_
    - _Verify: Run migrations, check schema_

- [ ] 2. Implement review API endpoints
    - GET /products/{id}/reviews
    - POST /products/{id}/reviews
    - _Requirements: 1.1, 2.1, 2.2_
    - _Verify: API returns 200, data matches schema_
```

### Phase 4: Implementation

During implementation:

1. **Work task by task** - Complete one task before moving to next
2. **Validate against criteria** - Check each acceptance criterion is satisfied
3. **Update specs if needed** - If requirements change, update specs first
4. **Mark progress** - Check off completed tasks

## Directory Structure

Create specs in `.specs/` directory:

```
.specs/
└── {feature-name}/
    ├── requirements.md
    ├── design.md
    └── tasks.md
```

## Execution Steps

### Step 1: Gather Context

Read the design principles to understand project standards:
```
DESIGN_PRINCIPLES.md
```

Read existing specs if any:
```
.specs/*/requirements.md
```

### Step 2: Generate Requirements

Create `.specs/{feature}/requirements.md`:

```markdown
# Requirements: {Feature Name}

## Introduction

{Brief description of the feature and its purpose}

## Requirements

### Requirement 1: {Capability Name}

**User Story:** As a {persona}, I want {capability}, so that {benefit}.

**Acceptance Criteria:**

1. WHEN {condition} THE SYSTEM SHALL {behavior}
2. WHEN {condition} THE SYSTEM SHALL {behavior}
...

### Requirement 2: {Capability Name}
...
```

### Step 3: Get User Approval

Present the requirements to the user:
- Show each user story
- Show acceptance criteria
- Ask for approval or modifications

Use AskUserQuestion if clarification needed on:
- Ambiguous requirements
- Missing edge cases
- Priority of features

### Step 4: Generate Design

After requirements approval, create `.specs/{feature}/design.md`:

```markdown
# Technical Design: {Feature Name}

## Overview

{High-level architecture description}

## Components

### {Component 1}

**Purpose:** {What this component does}
**Location:** `path/to/file.py`
**Changes:**
- {Change 1}
- {Change 2}

### {Component 2}
...

## Data Models

### {Model Name}

```python
@dataclass
class ModelName:
    field1: str  # Description
    field2: int  # Description
```

## Data Flow

1. User action triggers {event}
2. {Component A} receives request
3. {Component B} processes data
4. Result returned to user

## Error Handling

| Error Case | Response | Requirement |
|------------|----------|-------------|
| {Case 1} | {Action} | 1.3 |

## Testing Strategy

- Unit tests for {components}
- Integration tests for {flows}
- Edge case tests for {scenarios}
```

### Step 5: Generate Tasks

Create `.specs/{feature}/tasks.md`:

```markdown
# Implementation Plan: {Feature Name}

## Prerequisites

- [ ] Ensure dependencies are installed
- [ ] Read relevant existing code

## Tasks

- [ ] 1. {Task description}
    - {Substep 1}
    - {Substep 2}
    - _Requirements: {req numbers}_
    - _Verify: {how to verify}_

- [ ] 2. {Task description}
    - {Substep 1}
    - _Requirements: {req numbers}_
    - _Verify: {how to verify}_

## Verification

After all tasks complete:
- [ ] All acceptance criteria satisfied
- [ ] Tests pass: `./just test`
- [ ] Lint passes: `./just validate`
```

### Step 6: Implement

For each task:

1. Mark task as in-progress in TodoWrite
2. Implement the changes
3. Verify against linked requirements
4. Run tests: `./just dev | cat`
5. Mark task complete
6. Move to next task

### Step 7: Final Validation

After implementation:

1. Review all acceptance criteria - ensure each is satisfied
2. Run full test suite
3. Update documentation if needed
4. Mark feature complete

## Arguments

The skill accepts these arguments:

- `{feature description}` - Natural language description of feature to implement
- `requirements` - Only generate requirements (Phase 1)
- `design` - Generate design from existing requirements (Phase 2)
- `tasks` - Generate tasks from existing design (Phase 3)
- `implement` - Start implementation from existing tasks (Phase 4)
- `validate` - Validate implementation against acceptance criteria
- `sync` - Update specs based on code changes (bidirectional sync)

## Examples

```
/spec-driven Add ability to export data to CSV format
/spec-driven requirements  # Generate only requirements
/spec-driven implement     # Start implementing from existing specs
/spec-driven validate      # Check all acceptance criteria are met
```

## Integration with DESIGN_PRINCIPLES.md

When generating specs, ensure acceptance criteria align with project principles:

1. **Check relevant sections** - Reference the relevant design principle section for the component type
2. **Include compliance criteria** - Add criteria that verify principle compliance
3. **Link to principles** - Reference principle numbers in design rationale

Example:
```markdown
### Requirement 3: Data Storage

**Acceptance Criteria:**

1. WHEN data is received THE SYSTEM SHALL hash content (SHA-256) before storage
   _(Ref: DESIGN_PRINCIPLES.md 2.2 Deduplication)_
2. WHEN duplicate content is detected THE SYSTEM SHALL skip storage and log
   _(Ref: DESIGN_PRINCIPLES.md 2.2 Deduplication)_
```
