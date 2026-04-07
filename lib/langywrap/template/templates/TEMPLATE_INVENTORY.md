# Template Inventory

This document catalogs all reusable templates in this repository for initializing new projects.

## Template Files

### 1. README.md
**Purpose**: Project overview, quick start guide, and architecture diagram

**Location**: `/README.md`

**What it covers**:
- Project name and description
- Most used commands (quick reference)
- Quick start instructions
- Architecture overview
- Project structure
- External data sources and dependencies
- Quality & validation approach
- Development workflow
- Technology stack
- Claude Code skills (if any)

**Setup time**: 30-45 minutes

**Best for**: All projects

---

### 2. CLAUDE.md
**Purpose**: Guidance for Claude Code AI about your project's conventions and requirements

**Location**: `/CLAUDE.md`

**What it covers**:
- Project overview (for Claude)
- Important considerations (rate limits, security, performance)
- Command execution guidelines
- Development commands and workflows
- Main workflows (step-by-step)
- Configuration and environment variables
- Code organization & best practices
- Testing requirements
- Technology stack (detailed)
- Claude Code skills
- Common patterns & anti-patterns
- Data quality & validation (if applicable)
- Performance considerations
- Debugging & troubleshooting
- Documentation references

**Setup time**: 1-2 hours

**Best for**: Projects using Claude Code for development

**Tip**: This is the single most useful document for Claude Code. The effort pays off quickly.

---

### 3. DESIGN_PRINCIPLES.md
**Purpose**: Architectural design principles and acceptance criteria in EARS format

**Location**: `/DESIGN_PRINCIPLES.md`

**What it covers**:
- Custom design areas (3-5 per project)
- Principles with acceptance criteria in EARS format
- Code organization and naming conventions
- Testing & quality standards
- Configuration approach
- Error handling strategy
- Performance & scalability expectations
- Security & privacy requirements
- Component creation checklist
- Glossary of project-specific terms
- References to related documentation

**Setup time**: 2-4 hours (can be incremental)

**Best for**: Projects with significant architectural decisions

**Format**: Uses EARS notation (WHEN condition THE SYSTEM SHALL behavior)

---

### 4. justfile (template: justfile.template)
**Purpose**: Task automation for common development operations

**Location**: `/justfile` (copy from `justfile.template`)

**What it covers**:
- Setup commands (dependencies, initialization)
- Running/execution commands
- Testing commands (all tests, specific file, patterns, parallel)
- Code quality commands (lint, format, type check)
- Composite workflows (fix, validate, check, dev)
- Documentation building (optional)
- Cleaning/maintenance (optional)
- Project-specific operations (domain-dependent)
- Build/packaging (optional)
- Deployment (optional)

**Setup time**: 30 minutes - 1 hour

**Best for**: All projects (requires `just` command runner)

**Tool**: https://github.com/casey/just

---

### 5. TEMPLATE_GUIDE.md
**Purpose**: Step-by-step guide for using all templates in a new project

**Location**: `/TEMPLATE_GUIDE.md`

**What it covers**:
- Overview of all templates
- Step-by-step setup instructions
- Section-by-section guidance
- Examples for different project types
- Common mistakes to avoid
- Maintenance schedule
- Summary checklist

**Setup time**: Reference document (10-15 minutes to read)

**Best for**: New projects being initialized

---

### 6. TEMPLATE_INVENTORY.md (This File)
**Purpose**: Catalog of all templates and how to use them

**Location**: `/TEMPLATE_INVENTORY.md`

---

## How to Use These Templates

### For a New Project

1. **Copy templates** to your new project directory
2. **Read TEMPLATE_GUIDE.md** (10-15 minutes) to understand the process
3. **Follow the step-by-step guide** to customize each template
4. **Use `[INSTRUCTIONS]` blocks** in each file as guidance
5. **Test** that everything works (`just --list`, `./just dev`)
6. **Commit** to git

### For Existing Project

1. **Choose relevant templates** (e.g., you might skip DESIGN_PRINCIPLES.md initially)
2. **Adapt templates** to your project structure
3. **Focus on CLAUDE.md** first (biggest ROI if using Claude Code)
4. **Add justfile** to automate your workflows
5. **Document principles** as you discover patterns

---

## Template Customization Guidelines

### What to Replace

Every template has `[INSTRUCTIONS]` blocks and `[PLACEHOLDER]` sections. Replace:

| Placeholder | With |
|------------|------|
| `[PROJECT_NAME]` | Your actual project name |
| `[INSTRUCTIONS]` | Instructions for what to fill in |
| `[description]` | Your project-specific description |
| `[command]` | Your actual justfile commands |
| `[module_name]` | Your actual Python/code module names |

### What NOT to Replace

Keep these standard sections that apply to all projects:

- EARS notation format in DESIGN_PRINCIPLES.md
- Command preference order in CLAUDE.md
- Section headers and structure
- Verification commands pattern
- Testing guidelines

### Adapting by Project Type

**Data Pipeline**:
- Add data quality and lineage sections to DESIGN_PRINCIPLES.md
- Include scraping, ingestion, and transformation in justfile
- Document medallion architecture in README.md

**Web Application**:
- Add API design and database schema sections to DESIGN_PRINCIPLES.md
- Include database migrations and dev server in justfile
- Document deployment process in CLAUDE.md

**ML/Data Science**:
- Add model training and evaluation sections to justfile
- Document data leakage prevention in DESIGN_PRINCIPLES.md
- Include hyperparameter tuning workflows in CLAUDE.md

**CLI Tool**:
- Focus on command-line interface design in DESIGN_PRINCIPLES.md
- Include building and packaging in justfile
- Document usage patterns in README.md

---

## File Sizes and Scope

| File | Typical Size | Scope | Maintainability |
|------|------------|-------|-----------------|
| README.md | 2-4 KB | High-level overview | Easy (rarely changes) |
| CLAUDE.md | 5-10 KB | Medium detail | Medium (grows over time) |
| DESIGN_PRINCIPLES.md | 10-20 KB | Detailed principles | Medium (updated quarterly) |
| justfile | 2-5 KB | Commands | Easy (updated frequently) |
| TEMPLATE_GUIDE.md | 5-8 KB | Setup instructions | Easy (reference only) |

---

## Common Questions

### Q: Do I need all templates?

**A**: No, start with README.md and justfile. Add CLAUDE.md if using Claude Code. Add DESIGN_PRINCIPLES.md when architectural decisions stabilize.

### Q: How detailed should DESIGN_PRINCIPLES.md be?

**A**: Start with 3-5 core principles. Add more as you discover architectural patterns. Typical mature project has 10-15 principles.

### Q: Can I use these with different programming languages?

**A**: Yes! The templates are language-agnostic. Just replace the specific tool examples (ruff → eslint, pytest → jest, etc.).

### Q: Should I commit these files to git?

**A**: Yes! These are your project's documentation. They should be version controlled like code.

### Q: How often should I update these?

**A**: README.md: when architecture changes (quarterly). CLAUDE.md: as you discover patterns (weekly/monthly). DESIGN_PRINCIPLES.md: when making architectural decisions (as-needed). justfile: when adding workflows (frequently).

### Q: Can I delete sections I don't use?

**A**: Yes! Delete sections that don't apply to your project. For example, a CLI tool might not need a "Data Quality" section.

---

## Integration with Development Tools

### With justfile

Templates assume you're using `just` for task automation:

```bash
just --list        # See all commands
just sync          # Install dependencies
./just dev         # Full development cycle
```

### With Claude Code

CLAUDE.md teaches Claude Code about your project:

```bash
# Claude will use CLAUDE.md to understand:
# - Your command preferences
# - Your code organization
# - Your design patterns
# - Your testing approach
# - Your debugging tips
```

### With CI/CD

You can extract commands from justfile for CI/CD:

```yaml
# GitHub Actions example
- name: Run checks
  run: ./just check

- name: Run tests
  run: ./just test
```

---

## Best Practices

### DO ✅

- Keep documentation close to code (in same repo)
- Use consistent formatting across all documents
- Update docs when code changes
- Use examples that run and work
- Link between related sections
- Test instructions before committing
- Review documentation quarterly

### DON'T ❌

- Write overly long examples (keep to 10-15 lines max)
- Document implementation details (focus on "why")
- Let documentation get out of sync with code
- Over-specify things that might change (be flexible)
- Duplicate information across files (link instead)
- Use obscure formatting or special characters
- Create templates that are too rigid for adaptation

---

## Template Maturity Levels

### Level 1: Getting Started
- README.md ✅
- justfile ✅

### Level 2: Team Collaboration
- Level 1 + CLAUDE.md ✅

### Level 3: Mature Project
- Level 2 + DESIGN_PRINCIPLES.md ✅

### Level 4: Multiple Teams
- Level 3 + Architecture docs, API docs, deployment guides ✅

---

## Next Steps

1. **Review TEMPLATE_GUIDE.md** - Understand the step-by-step process
2. **Copy templates** to your new project
3. **Fill in README.md** first (fastest ROI)
4. **Add justfile** commands for your workflow
5. **Create CLAUDE.md** if using Claude Code
6. **Document DESIGN_PRINCIPLES.md** as architecture stabilizes
7. **Test everything** works
8. **Commit to git**

---

## Template Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-12-XX | Initial templates created |
| | | - README.md with project overview structure |
| | | - CLAUDE.md with Claude Code guidance |
| | | - DESIGN_PRINCIPLES.md with EARS format |
| | | - justfile.template with common commands |
| | | - TEMPLATE_GUIDE.md with setup instructions |

---

## License

These templates are provided as-is for use in your projects. Feel free to modify, extend, and adapt them to your needs.

---

## Support

For questions about using these templates:
1. Review the relevant `[INSTRUCTIONS]` blocks in each template
2. Check TEMPLATE_GUIDE.md for examples
3. Look at your project's specific needs and adapt accordingly

These templates are designed to be flexible starting points, not rigid frameworks. Customize them for your project!
