"""Migrate legacy heading-form tasks.md to the unified checkbox format.

Two legacy shapes commonly seen in early ralph adopters that the
unified-format lint expects to migrate forward:

  ``### [Pn-X] Title <!-- task:slug -->``
      Heading with bracketed priority + single-letter type code (R / L /
      H ...), task slug in an HTML comment. The default type-code map is
      ``R->research``, ``L->lean``, ``H->hygiene``; callers can override.

  ``### [ ] **[Pn] task:slug** [type] Title``
  ``### [x] **[Pn] task:slug** [type] Title``
      Same body as the canonical line, but using ``###`` heading prefix
      instead of a ``- [ ]`` / ``- [x]`` checkbox bullet.

Canonical target line::

    - [ ] **[P0] task:slug-name** [task_type] Human label

Lines already in canonical shape pass through unchanged. Anything else
is left alone with a warning so the caller can inspect.

Usage::

    python -m langywrap.ralph.migrate_tasks path/to/tasks.md \\
        --types R=research,L=lean,H=hygiene

    python -m langywrap.ralph.migrate_tasks path/to/tasks.md --dry-run

The default type-code map covers the BSDconj migration's R/L/H codes;
override via ``--types`` for projects with different conventions.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TYPE_MAP: dict[str, str] = {
    "R": "research",
    "L": "lean",
    "H": "hygiene",
}

# `### [Pn-X] Title <!-- task:slug -->`
_HEADING_BRACKETED_RE = re.compile(
    r"^###\s+\[P(\d)-([A-Z])\]\s+(.+?)\s*<!--\s*task:([a-z][\w-]*)\s*-->\s*$"
)

# `### [ ]/[x] **[Pn] task:slug** [type] Title`
_HEADING_CHECKBOX_RE = re.compile(
    r"^###\s+\[( |x)\]\s+\*\*\[P(\d)\]\s+task:([a-z][\w-]*)\*\*\s+\[([a-z_][\w_]*)\]\s+(.*?)\s*$"
)

# Canonical: `- [ ]/[x] **[Pn] task:slug** [type] Title`
_CANONICAL_RE = re.compile(
    r"^- \[( |x)\]\s+\*\*\[P\d\]\s+task:[a-z][\w-]*\*\*\s+\[[a-z_][\w_]*\]\s+.*$"
)


@dataclass
class MigrationReport:
    """Outcome of a tasks.md migration.

    Attributes:
        migrated_text: New file content (unchanged if no edits applied).
        bracketed_count: Lines matched by the ``### [Pn-X]`` form.
        heading_checkbox_count: Lines matched by the ``### [ ]/[x] **...**``
            form.
        canonical_count: Lines already in unified shape (no-op).
        unmapped_codes: Type-code letters present in the source but absent
            from the ``type_map``. The lines stay unchanged in the output.
        warnings: Human-readable notes (e.g. unmapped codes, suspect lines).
    """

    migrated_text: str
    bracketed_count: int = 0
    heading_checkbox_count: int = 0
    canonical_count: int = 0
    unmapped_codes: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_migrations(self) -> int:
        return self.bracketed_count + self.heading_checkbox_count

    def render(self) -> str:
        lines = [
            f"Migrated lines: {self.total_migrations} "
            f"(bracketed: {self.bracketed_count}, "
            f"heading-checkbox: {self.heading_checkbox_count})",
            f"Already canonical: {self.canonical_count}",
        ]
        if self.unmapped_codes:
            lines.append(
                "Unmapped type codes (lines kept unchanged): "
                + ", ".join(sorted(self.unmapped_codes))
            )
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        return "\n".join(lines)


def migrate(
    text: str,
    type_map: dict[str, str] | None = None,
) -> MigrationReport:
    """Apply the migration to ``text`` and return a :class:`MigrationReport`.

    Args:
        text: Original tasks.md content.
        type_map: Maps single-letter type codes (used in the ``[Pn-X]``
            heading form) to full type names. Defaults to
            ``{"R": "research", "L": "lean", "H": "hygiene"}``.
    """
    tmap = type_map if type_map is not None else dict(DEFAULT_TYPE_MAP)
    bracketed = 0
    heading_cb = 0
    canonical = 0
    unmapped: set[str] = set()
    warnings: list[str] = []

    out: list[str] = []
    for line in text.splitlines():
        if _CANONICAL_RE.match(line):
            canonical += 1
            out.append(line)
            continue

        m = _HEADING_BRACKETED_RE.match(line)
        if m:
            priority, code, title, slug = m.group(1), m.group(2), m.group(3), m.group(4)
            type_name = tmap.get(code)
            if type_name is None:
                unmapped.add(code)
                out.append(line)
                continue
            out.append(f"- [ ] **[P{priority}] task:{slug}** [{type_name}] {title}")
            bracketed += 1
            continue

        m = _HEADING_CHECKBOX_RE.match(line)
        if m:
            status, priority, slug, type_name, title = m.groups()
            out.append(f"- [{status}] **[P{priority}] task:{slug}** [{type_name}] {title}")
            heading_cb += 1
            continue

        # Anything that LOOKS like a tasks.md task heading but doesn't match
        # — surface a soft warning so the user can audit by hand.
        if line.startswith("### ") and ("task:" in line or re.search(r"\[P\d", line)):
            warnings.append(f"line not migrated (unrecognised shape): {line.strip()[:120]}")
        out.append(line)

    new_text = "\n".join(out)
    if text.endswith("\n"):
        new_text += "\n"
    return MigrationReport(
        migrated_text=new_text,
        bracketed_count=bracketed,
        heading_checkbox_count=heading_cb,
        canonical_count=canonical,
        unmapped_codes=unmapped,
        warnings=warnings,
    )


def _parse_type_map(s: str) -> dict[str, str]:
    """Parse ``--types R=research,L=lean,H=hygiene`` into a dict."""
    out: dict[str, str] = {}
    for pair in s.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"--types entries must be CODE=name, got: {pair!r}")
        code, name = pair.split("=", 1)
        code, name = code.strip(), name.strip()
        if len(code) != 1 or not code.isalpha():
            raise ValueError(f"type-code must be a single letter, got: {code!r}")
        out[code.upper()] = name
    return out


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="langywrap.ralph.migrate_tasks",
        description=(
            "Migrate legacy heading-form tasks.md to the unified "
            "`- [ ] **[Pn] task:slug** [type] label` shape."
        ),
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--types",
        default="",
        help=(
            "Override type-code map, e.g. R=research,L=lean,H=hygiene "
            "(default). Single-letter codes only."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report and the diff stats; do not write back.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.path.exists():
        print(f"migrate_tasks: path not found: {args.path}", file=sys.stderr)
        return 2

    try:
        type_map = _parse_type_map(args.types) if args.types else None
    except ValueError as exc:
        print(f"migrate_tasks: {exc}", file=sys.stderr)
        return 2

    text = args.path.read_text(encoding="utf-8")
    report = migrate(text, type_map=type_map)
    print(report.render())

    if report.migrated_text == text:
        return 0

    if args.dry_run:
        print("(dry-run: file not modified)")
        return 0

    args.path.write_text(report.migrated_text, encoding="utf-8")
    return 0


__all__ = [
    "DEFAULT_TYPE_MAP",
    "MigrationReport",
    "main",
    "migrate",
]


if __name__ == "__main__":
    sys.exit(main())
