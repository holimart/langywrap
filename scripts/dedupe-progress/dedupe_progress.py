"""One-shot historical cleanup for `progress.md` files corrupted by the
pre-2026-05-15 dual-writer bug.

Usage:
    uv run python scripts/dedupe-progress/dedupe_progress.py path/to/progress.md
    uv run python scripts/dedupe-progress/dedupe_progress.py path/to/progress.md --apply

By default this is a dry run — it prints the dedup report and writes the
deduplicated file to `<path>.deduped` for review. Pass `--apply` to
overwrite the original in place (a `.bak` is left next to it).

Multiple paths are accepted; report is per-file.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from langywrap.ralph.progress_dedupe import dedupe_progress


def process(path: Path, *, apply: bool) -> int:
    """Return exit code (0 = ok, 2 = file missing)."""
    if not path.exists():
        print(f"[skip] {path}: not found")
        return 2
    text = path.read_text(encoding="utf-8")
    deduped, report = dedupe_progress(text)
    print(
        f"[{path}] "
        f"cycles_with_duplicates={report.cycles_with_duplicates} "
        f"blocks_removed={report.blocks_removed} "
        f"blocks_kept={report.blocks_kept} "
        f"metric_lines_merged={report.metric_lines_merged}"
    )
    if deduped == text:
        print(f"  → already clean, no changes")
        return 0
    if apply:
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        path.write_text(deduped, encoding="utf-8")
        print(f"  → applied. Backup at {bak}")
    else:
        out = path.with_suffix(path.suffix + ".deduped")
        out.write_text(deduped, encoding="utf-8")
        print(f"  → dry run. Preview at {out}. Pass --apply to overwrite.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Overwrite the file in place (keeps a .bak next to it).",
    )
    args = ap.parse_args()
    rc = 0
    for p in args.paths:
        rc = max(rc, process(p, apply=args.apply))
    return rc


if __name__ == "__main__":
    sys.exit(main())
