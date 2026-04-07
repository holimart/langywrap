# Template Setup Guide

This guide explains how to use the template files in this repository to quickly set up documentation and task automation for a new project.

## Overview

This repository contains reusable templates for any software project:

| File | Purpose | Use When |
|------|---------|----------|
| **README.md** | Project overview, quick start, architecture | All projects |
| **CLAUDE.md** | Claude Code guidance and conventions | Using Claude Code for development |
| **DESIGN_PRINCIPLES.md** | Design rules and acceptance criteria | Documenting architecture decisions |
| **justfile** | Task automation for common operations | Using the `just` command runner |

All templates use `[INSTRUCTIONS]` blocks to guide you through customization.

---

## Step-by-Step Setup for a New Project

### Step 1: Copy Templates

```bash
# Copy templates to your new project
cp README.md /path/to/new-project/
cp CLAUDE.md /path/to/new-project/
cp DESIGN_PRINCIPLES.md /path/to/new-project/
cp justfile.template /path/to/new-project/justfile
```

### Step 2: Fill in README.md

This is your project's front door. In order:

1. **Replace `[PROJECT_NAME]`** with your actual project name
2. **Write the description** (2-3 sentences explaining what your project does)
3. **Fill in "Most Used Commands"** with your actual justfile commands
4. **Fill in "Quick Start"** with setup and first-run instructions
5. **Draw your "Architecture Overview"** (ASCII diagram or text flow)
6. **Update "Project Structure"** to match your directory layout
7. **List "Data Sources / External Dependencies"** (APIs, databases, etc.)
8. **Describe "Quality & Validation"** (what checks you run)
9. **Update "Technology Stack"** with your actual tools
10. **List "Claude Code Skills"** if you created any custom `/slash` commands

**Time estimate**: 30-45 minutes for a typical project

**Tip**: Start with a minimal version and expand as your project grows.

### Step 3: Fill in CLAUDE.md

This teaches Claude Code about your project's conventions. Follow these sections:

1. **Project Overview** - What is this project? (copy from README)
2. **Important Considerations** - What should Claude never do? (rate limits, security, performance traps)
3. **Command Execution Guidelines** - Table of your common tasks and preferred commands
4. **Development Commands** - What are your main workflows?
5. **Main Workflows** - Detailed step-by-step for complex operations
6. **Configuration** - Environment variables and settings
7. **Code Organization** - Where do things go? Naming conventions?
8. **Testing Requirements** - What coverage/testing approach do you use?
9. **Technology Stack** - Same as README, but with more detail
10. **Claude Code Skills** - Custom `/slash` commands you've created
11. **Common Patterns & Anti-Patterns** - Code examples of good vs bad practices
12. **Data Quality & Validation** - (if applicable)
13. **Performance Considerations** - (if applicable)
14. **Debugging & Troubleshooting** - Common issues and how to fix them
15. **Documentation References** - Links to other docs

**Time estimate**: 1-2 hours. This is comprehensive but well worth it.

**Tip**: CLAUDE.md gets better over time. Start with the essentials, add sections as you discover patterns.

### Step 4: Fill in DESIGN_PRINCIPLES.md

This documents your architecture decisions for future reference.

1. **Update Table of Contents** - Replace placeholder sections with your actual design areas
   - Examples: "Data Flow Architecture", "API Design", "Error Handling", "Performance", "Security"
2. **For each design area**, add 2-5 principles
3. **For each principle**, write:
   - **Principle**: One clear statement of the rule
   - **Acceptance Criteria**: 3-5 EARS-format sentences (WHEN X THE SYSTEM SHALL Y)
   - **Examples**: Code or configuration showing the right way
4. **Fill in standard sections**: Code Organization, Testing & Quality, Configuration, Error Handling
5. **Add project-specific sections**: Security, Performance, Data Validation, etc.
6. **Create "Adding New Components Checklist"** - What must developers do when adding features?

**Time estimate**: 2-4 hours. Can be incremental.

**Tip**: Start with 3-4 core principles. Add more as you discover architectural patterns.

**Format reminder**: Always use EARS format for acceptance criteria:
```
WHEN [condition] THE SYSTEM SHALL [expected behavior]
```

### Step 5: Create your justfile

Use `justfile.template` as a starting point:

1. **Copy template**: `cp justfile.template justfile`
2. **Keep these sections**: SETUP, TESTING, CODE QUALITY, WORKFLOWS, CLEANING
3. **Replace these with your commands**:
   - RUNNING section → your main operations (scrape, build, train, serve, etc.)
   - PROJECT-SPECIFIC section → domain-specific commands
   - Optional sections → BUILD, DEPLOYMENT, DOCUMENTATION (only if needed)
4. **For each command**, write a helpful comment

**Template structure**:
```
# Section comment
# ============================================================================

# Help text for this command (shown in `just --list`)
command-name:
    ./uv run python -m module

# Another command
another-command with params:
    ./uv run python script.py {{param}}
```

**Common commands by project type**:

**Data Pipeline**:
```bash
scrape            # Fetch data from sources
ingest            # Process raw data → parquet
transform         # Transform data layers
validate          # Check data quality
```

**Web Application**:
```bash
serve             # Run dev server
build             # Build for production
migrate           # Run database migrations
seed-db           # Populate test data
```

**ML/Data Science**:
```bash
train             # Train the model
evaluate          # Run evaluation metrics
predict           # Generate predictions
tune              # Hyperparameter optimization
```

**CLI Tool**:
```bash
build             # Build binary/package
install           # Install locally
test-install      # Test the installation
publish           # Release to package manager
```

**Time estimate**: 30 minutes to 1 hour

**Tip**: Start with 10-15 essential commands. Add more as your workflow evolves.

---

## Template Sections Reference

### README.md Sections

| Section | What to fill | Examples |
|---------|------------|----------|
| `[PROJECT_NAME]` | Your project's actual name | "MyWebApp", "DataPipeline", "ImageClassifier" |
| `[command1]`, `[command2]` | Your most-used justfile commands | `./just test`, `./just dev`, `./just deploy` |
| Architecture Overview | How data/requests flow through your system | ASCII diagram, pipeline stages, component relationships |
| Project Structure | Your directory organization | `src/`, `tests/`, `scripts/`, `docs/` |
| Data Sources | External APIs and databases you use | "Stripe API", "PostgreSQL", "S3 buckets" |
| Quality & Validation | What quality checks you run | Linting, type checking, tests, data validation |

### CLAUDE.md Sections

| Section | What to fill | When to use |
|---------|------------|-----------|
| Important Considerations | Warnings about rate limits, security, performance | Always |
| Command Execution Guidelines | Your most common tasks and how to do them | Always |
| Main Workflows | Step-by-step for complex operations | If your project has multi-step processes |
| Code Organization | Where code goes, naming conventions | Always |
| Common Patterns | Code examples of right and wrong ways | If you have domain-specific patterns |
| Data Quality | Quality standards and validation | If your project involves data |
| Performance | Critical paths and optimization | If performance matters (web apps, big data) |
| Debugging | Common issues and how to fix them | Add as you discover problems |

### DESIGN_PRINCIPLES.md Sections

| Section | What to fill | When to use |
|---------|------------|-----------|
| Custom design areas | Your architectural principles | Always (3-4 minimum) |
| Code Organization | Module structure, naming, documentation | Always |
| Testing & Quality | Test coverage expectations | Always |
| Error Handling | How errors are handled and reported | Always |
| Performance & Scalability | Response time, memory, throughput targets | If performance matters |
| Security & Privacy | Input validation, data protection | If handling sensitive data |

### justfile Sections

| Section | What to fill | When to use |
|---------|------------|-----------|
| SETUP | Install dependencies, initialize environment | All projects |
| RUNNING | Your main application operations | All projects |
| TESTING | How to run tests in various modes | All projects |
| CODE QUALITY | Linting, formatting, type checking | All projects |
| WORKFLOWS | Composite commands (fix, check, dev) | All projects |
| PROJECT-SPECIFIC | Your domain-specific operations | Almost all projects |
| DOCUMENTATION | Build and serve docs | If you have docs |
| CLEANING | Clean cache and build artifacts | Most projects |
| DEPLOYMENT | Deploy to production | If you deploy |

---

## Usage Examples

### Example 1: Python Web Application

**README.md**:
```markdown
# MyWebApp

A FastAPI web application for managing user tasks.

## Most Used Commands

| Command | What it does |
|---------|-------------|
| `./just serve` | Start development server |
| `./just test` | Run all tests |
| `./just migrate` | Run database migrations |
| `./just dev` | Development cycle: format, lint, test |
```

**CLAUDE.md**:
```markdown
## Important Considerations
- Database queries should use parameterized queries to prevent SQL injection
- API responses must validate input before processing
- Rate limit authentication endpoints (10 requests per minute per IP)
```

**justfile**:
```bash
serve:
    ./uv run fastapi dev main.py

migrate:
    ./uv run alembic upgrade head

seed-db:
    ./uv run python scripts/seed.py
```

### Example 2: Data Pipeline

**README.md**:
```markdown
# DataPipeline

Processes data from multiple sources and produces analysis-ready datasets.

## Most Used Commands

| Command | What it does |
|---------|-------------|
| `./just orchestrate` | Scrape all data sources |
| `./just ingest-all` | Build data layers (bronze/silver/gold) |
| `./just lineage-validate` | Verify data flow connections |
```

**CLAUDE.md**:
```markdown
## Important Considerations
- External APIs may have rate limits (e.g., 8 requests/second for some services)
- Use DuckDB for queries on 100K+ rows, not pandas (10x faster)
- Data leakage is the #1 bug: always use ASOF joins with correct direction
```

**DESIGN_PRINCIPLES.md**:
```markdown
## 1. Data Flow Architecture

### 1.1 Medallion Architecture
**Principle**: Data flows through Bronze → Silver → Gold layers with increasing refinement.

**Acceptance Criteria**:
1. WHEN raw data is downloaded THE SYSTEM SHALL store it unchanged in ingest/
2. WHEN bronze layer processes data THE SYSTEM SHALL convert JSON to Parquet
3. WHEN silver layer processes data THE SYSTEM SHALL apply transformations
4. WHEN gold layer produces output THE SYSTEM SHALL be analysis-ready
```

### Example 3: ML/Data Science Project

**justfile**:
```bash
train:
    ./uv run python -m scripts.train

evaluate:
    ./uv run python -m scripts.evaluate

tune:
    ./uv run python -m scripts.tune_hyperparameters --regime bull

predict:
    ./uv run python -m scripts.predict --date today
```

---

## Common Mistakes to Avoid

1. **Over-documenting too early**: Start with essentials, expand as you learn patterns
2. **Documenting what, not why**: Focus on principles and reasons, not just procedures
3. **Forgetting to update docs**: Set a reminder to review documentation quarterly
4. **Making justfile commands too complex**: Keep each command simple; chain them for complexity
5. **Ignoring EARS format**: It might seem rigid, but it prevents ambiguity
6. **Not tailoring to your project**: These are templates, not rules. Adapt!

---

## Maintenance

As your project evolves:

- **Monthly**: Review CLAUDE.md and add new patterns you discover
- **Quarterly**: Update DESIGN_PRINCIPLES.md as architecture changes
- **Weekly**: Update justfile when you add new workflows
- **Always**: Keep README.md current with latest technology and best practices

---

## Questions?

Each template file has `[INSTRUCTIONS]` blocks to guide you. If a section doesn't apply to your project, you can:

1. **Delete it** (if optional)
2. **Adapt it** (modify for your context)
3. **Leave it as template** (fill in later when relevant)

The goal is to have documentation that's **useful and maintainable**, not perfect.

---

## Summary Checklist

- [ ] Copied all templates to new project
- [ ] Filled in README.md (project overview, commands, architecture)
- [ ] Filled in CLAUDE.md (conventions, workflows, patterns)
- [ ] Created DESIGN_PRINCIPLES.md (architectural principles)
- [ ] Created justfile (task automation)
- [ ] Tested that `just --list` shows all commands
- [ ] Tested that `./just dev` works end-to-end
- [ ] Reviewed documentation for clarity

**Next step**: Commit these files to git and start using them!
