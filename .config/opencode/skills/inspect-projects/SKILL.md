---
name: inspect-projects
description: Quickly status or deeply diagnose Ralph-coupled projects from LANGYWRAP_PROJECTS
license: MIT
compatibility: opencode
metadata:
  audience: agents
  purpose: project-inspection
---

# Inspect Ralph Projects

Use this skill to inspect projects registered in langywrap's repo-root `.env`.
It wraps `scripts/inspect-projects/inspect_projects.py` and returns either a fast
status table or a deeper debugging bundle for later analysis.

See `skills/inspect-projects/SKILL.md` for the full workflow. This local copy is
installed here so OpenCode can discover the skill from the project-local skill
directory.
