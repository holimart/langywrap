# Design Principles & Acceptance Criteria

This document consolidates all architectural design principles across the project. Each principle includes acceptance criteria in **EARS (Easy Approach to Requirements Syntax)** notation for unambiguous verification.

**Instructions**: This is a template for documenting your project's design principles. Replace each `[INSTRUCTIONS]` section with your project-specific principles and criteria. Keep the EARS format for consistency.

## EARS Notation Reference

```
WHEN [condition/event] THE SYSTEM SHALL [expected behavior]
```

This format provides clarity and reduces misinterpretation. Each criterion is testable and enforceable.

## How to Use This Template

1. **Identify your project's key design areas** (see Table of Contents below for examples)
2. **For each area**, write one principle statement (1-2 sentences explaining the rule)
3. **List acceptance criteria** using the EARS format
4. **Add examples** for complex principles
5. **Link to verification commands** (tests, linters, checks)

## Table of Contents

**[INSTRUCTIONS]**: Update this list with your project's design areas. Replace the placeholder sections with your actual architectural concerns.

1. [Your Design Area 1](#1-your-design-area-1)
2. [Your Design Area 2](#2-your-design-area-2)
3. [Your Design Area 3](#3-your-design-area-3)
4. [Code Organization](#4-code-organization)
5. [Testing & Quality](#5-testing--quality)
6. [Configuration](#6-configuration)

---

## 1. Your Design Area 1

**[INSTRUCTIONS]**: Provide a short title for your first major design principle area. Examples: "Data Flow Architecture", "API Design", "Error Handling", "Performance", "Security", etc.

### 1.1 First Principle

**Principle**: [One clear statement of the rule. Example: "All data flows through a three-stage pipeline with progressive refinement."]

**Acceptance Criteria**:

1. WHEN [condition] THE SYSTEM SHALL [expected behavior]
2. WHEN [condition] THE SYSTEM SHALL [expected behavior]
3. WHEN [condition] THE SYSTEM SHALL [expected behavior]

**Example**:
```
[Code or configuration example showing the correct pattern]
```

### 1.2 Second Principle

**Principle**: [Next principle statement]

**Acceptance Criteria**:

1. WHEN [condition] THE SYSTEM SHALL [expected behavior]
2. WHEN [condition] THE SYSTEM SHALL [expected behavior]

---

## 2. Your Design Area 2

**[INSTRUCTIONS]**: Add another major design area with its principles and criteria.

### 2.1 First Principle in This Area

**Principle**: [Principle statement]

**Acceptance Criteria**:

1. WHEN [condition] THE SYSTEM SHALL [expected behavior]
2. WHEN [condition] THE SYSTEM SHALL [expected behavior]

### 2.2 Second Principle

**Principle**: [Principle statement]

**Acceptance Criteria**:

1. WHEN [condition] THE SYSTEM SHALL [expected behavior]
2. WHEN [condition] THE SYSTEM SHALL [expected behavior]

---

## 3. Your Design Area 3

**[INSTRUCTIONS]**: Add more design areas as needed. Examples:
- API Design Principles
- Database Design
- Caching Strategy
- Error Handling
- Concurrency & Threading
- Memory Management
- Security
- Backwards Compatibility

### 3.1 Principle Name

**Principle**: [Principle statement]

**Acceptance Criteria**:

1. WHEN [condition] THE SYSTEM SHALL [expected behavior]
2. WHEN [condition] THE SYSTEM SHALL [expected behavior]

---

## 4. Code Organization

**[INSTRUCTIONS]**: Document how code should be organized in this project.

### 4.1 Module Structure

**Principle**: Code is organized into clear modules by responsibility, with minimal cross-dependencies.

**Acceptance Criteria**:

1. WHEN a new module is created THE SYSTEM SHALL have a clear, single responsibility
2. WHEN modules communicate THE SYSTEM SHALL use dependency injection, not global state
3. WHEN code is added THE SYSTEM SHALL follow the established package structure

**[INSTRUCTIONS]**: Add your specific module organization rules here.

### 4.2 Naming Conventions

**Principle**: Consistent naming makes code self-documenting and enables better tooling.

**Acceptance Criteria**:

1. WHEN naming variables THE SYSTEM SHALL use [your convention, e.g., snake_case in Python]
2. WHEN naming functions THE SYSTEM SHALL use [your convention]
3. WHEN naming classes THE SYSTEM SHALL use [your convention]
4. WHEN naming constants THE SYSTEM SHALL use [your convention]

**[INSTRUCTIONS]**: Add your project's naming standards.

### 4.3 Documentation Requirements

**Principle**: All components have sufficient documentation for another developer to understand and use them.

**Acceptance Criteria**:

1. WHEN a public function is created THE SYSTEM SHALL include a docstring explaining purpose, parameters, and return value
2. WHEN a module is created THE SYSTEM SHALL include a module-level docstring explaining its responsibility
3. WHEN complex logic is used THE SYSTEM SHALL include comments explaining why (not what)
4. WHEN a component is updated THE SYSTEM SHALL update its documentation

---

## 5. Testing & Quality

**[INSTRUCTIONS]**: Document your testing expectations and quality standards.

### 5.1 Unit Testing

**Principle**: All components are covered by automated tests to enable safe refactoring.

**Acceptance Criteria**:

1. WHEN new code is written THE SYSTEM SHALL include tests for normal cases
2. WHEN new code is written THE SYSTEM SHALL include tests for edge cases and error conditions
3. WHEN tests are run THE SYSTEM SHALL achieve [your coverage target, e.g., 80%] coverage
4. WHEN a test fails THE SYSTEM SHALL be clear why without reading the implementation

**[INSTRUCTIONS]**: Add your testing requirements.

### 5.2 Code Quality Checks

**Principle**: Automated tools enforce code quality standards consistently.

**Acceptance Criteria**:

1. WHEN code is committed THE SYSTEM SHALL pass linting checks
2. WHEN code is committed THE SYSTEM SHALL pass type checking
3. WHEN code is committed THE SYSTEM SHALL pass formatting standards
4. WHEN `./just dev` is run THE SYSTEM SHALL fix and verify all quality checks

**[INSTRUCTIONS]**: List your actual quality tools and commands.

### 5.3 Performance Testing

**Principle**: [Your performance principle - optional if applicable]

**Acceptance Criteria**:

1. WHEN [performance-critical operation] is performed THE SYSTEM SHALL complete within [acceptable time]
2. WHEN [resource-intensive operation] runs THE SYSTEM SHALL use less than [acceptable memory]

**[INSTRUCTIONS]**: Add performance requirements for critical paths.

---

## 6. Configuration

**[INSTRUCTIONS]**: Document your configuration approach.

### 6.1 Environment-Based Configuration

**Principle**: All runtime configuration is externalized via environment variables, not hardcoded.

**Acceptance Criteria**:

1. WHEN the application starts THE SYSTEM SHALL load configuration from `.env` file or environment variables
2. WHEN a required config is missing THE SYSTEM SHALL fail with a clear error message
3. WHEN an invalid config value is provided THE SYSTEM SHALL fail validation at startup, not at runtime
4. WHEN deploying to different environments THE SYSTEM SHALL require no code changes (config only)

**[INSTRUCTIONS]**: Add your configuration requirements.

### 6.2 Default Values

**Principle**: Sensible defaults reduce configuration burden while allowing customization.

**Acceptance Criteria**:

1. WHEN a config value is not set THE SYSTEM SHALL use a documented default value
2. WHEN defaults are not suitable THE SYSTEM SHALL be easy for the user to override
3. WHEN defaults change THE SYSTEM SHALL be documented in CHANGELOG with migration guide

---

## 7. Error Handling

**[INSTRUCTIONS]**: Document how errors should be handled in your project.

### 7.1 Error Messages

**Principle**: Error messages help developers understand and fix problems quickly.

**Acceptance Criteria**:

1. WHEN an error occurs THE SYSTEM SHALL include a clear description of what went wrong
2. WHEN an error occurs THE SYSTEM SHALL suggest how to fix it (when applicable)
3. WHEN an error occurs THE SYSTEM SHALL include relevant context (values, file names, etc.)
4. WHEN logging errors THE SYSTEM SHALL use appropriate log levels (WARNING, ERROR, CRITICAL)

---

## 8. Performance & Scalability

**[INSTRUCTIONS]**: Document performance expectations and optimization guidelines.

### 8.1 Memory Usage

**Principle**: [Your memory principle - e.g., "Process large datasets in batches to bound memory usage"]

**Acceptance Criteria**:

1. WHEN processing [your operation] THE SYSTEM SHALL use O(batch_size) memory, not O(total_size)
2. WHEN handling large inputs THE SYSTEM SHALL process in configurable batches
3. WHEN batches are configured THE SYSTEM SHALL allow tuning via [configuration method]

### 8.2 Response Time

**Principle**: [Your latency principle - e.g., "Critical operations respond within acceptable time bounds"]

**Acceptance Criteria**:

1. WHEN [critical operation] is performed THE SYSTEM SHALL respond within [timeframe, e.g., 100ms]
2. WHEN [heavy operation] is performed THE SYSTEM SHALL complete within [longer timeframe, e.g., 5 minutes]
3. WHEN timeouts occur THE SYSTEM SHALL provide meaningful error messages

---

## 9. Security & Privacy

**[INSTRUCTIONS]**: Document security and privacy expectations if applicable.

### 9.1 Input Validation

**Principle**: All external input is validated at system boundaries before use.

**Acceptance Criteria**:

1. WHEN external input is received THE SYSTEM SHALL validate [your validation rules]
2. WHEN invalid input is detected THE SYSTEM SHALL reject it with clear error message
3. WHEN validation fails THE SYSTEM SHALL never use the input

### 9.2 Sensitive Data Handling

**Principle**: [Your principle - e.g., "Sensitive data is never logged or exposed in errors"]

**Acceptance Criteria**:

1. WHEN [sensitive data] is handled THE SYSTEM SHALL [your protection method]
2. WHEN errors occur THE SYSTEM SHALL not expose [sensitive data types]
3. WHEN debugging THE SYSTEM SHALL provide [your debug approach] without compromising security

---

## Verification & Testing

**[INSTRUCTIONS]**: Document how to verify these principles are met.

```bash
# Code quality verification
./just dev                    # Auto-fix + full checks
./just check                  # Verify all checks pass

# Testing
./just test                   # Run all tests
./just test-file <path>       # Run specific test

# Custom verifications
[List any project-specific verification commands]
```

---

## Adding New Components Checklist

**[INSTRUCTIONS]**: Provide a checklist for developers adding new components.

### New [Component Type] Checklist

| Step | Requirement |
|------|-------------|
| 1 | [Create file/module at proper location] |
| 2 | [Follow naming conventions] |
| 3 | [Add docstring/comments] |
| 4 | [Create unit tests] |
| 5 | [Update documentation] |
| 6 | [Pass linting and type checks] |
| 7 | [Achieve [coverage] % test coverage] |

### Verification

```bash
./just dev                    # All checks pass
./just test                   # All tests pass
[Any custom verification commands]
```

---

## Glossary

**[INSTRUCTIONS]**: Define project-specific terms that appear in this document.

| Term | Definition |
|------|-----------|
| [Your term] | [Definition] |
| [Your term] | [Definition] |

---

## References & Related Documents

**[INSTRUCTIONS]**: Link to related documentation.

- **[README.md](README.md)** - Project overview and quick start
- **[CLAUDE.md](CLAUDE.md)** - Claude Code guidance
- **[Architecture Documentation]** - Detailed architecture (if separate file)
- **[API Documentation]** - API design principles (if applicable)

---

## Document History

**[INSTRUCTIONS]**: Track significant updates to this document.

| Date | Change | Author |
|------|--------|--------|
| [YYYY-MM-DD] | Initial template creation | [Your name] |
| [YYYY-MM-DD] | [Description of change] | [Your name] |
