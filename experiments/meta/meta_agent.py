#!/usr/bin/env python3
"""Standalone meta-agent for evolving agent configurations.

Can be run directly or called from ralph loop's finalize step.

Usage:
    python meta_agent.py --exploit          # Use best config
    python meta_agent.py --explore          # Use mutated variant
    python meta_agent.py --evolve           # Run one evolution step
    python meta_agent.py --status           # Show archive status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add lib to path for standalone execution
_lib_dir = Path(__file__).resolve().parent.parent.parent / "lib"
if str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))


def get_archive_dir() -> Path:
    """Find archive directory."""
    langywrap_root = Path(__file__).resolve().parent.parent.parent
    return langywrap_root / "experiments" / "archive"


def cmd_status(args: argparse.Namespace) -> None:
    """Show archive status."""
    from langywrap.hyperagents.archive import Archive

    archive = Archive(get_archive_dir())
    variants = archive.all_variants()

    print(f"Archive: {get_archive_dir()}")
    print(f"Total variants: {len(variants)}")

    if not variants:
        print("Empty archive. Run --evolve to create seed variant.")
        return

    best = archive.get_best(5)
    print("\nTop 5 by fitness:")
    for v in best:
        print(
            f"  {v.id} gen={v.generation} fitness={v.fitness_score:.4f} "
            f"origin={v.project_origin} mutations={v.mutations}"
        )

    generations = [v.generation for v in variants]
    print(f"\nGeneration range: {min(generations)} - {max(generations)}")
    origins = set(v.project_origin for v in variants if v.project_origin)
    print(f"Project origins: {origins or 'none'}")


def cmd_exploit(args: argparse.Namespace) -> None:
    """Output best config for production use."""
    from langywrap.hyperagents.archive import Archive

    archive = Archive(get_archive_dir())
    best = archive.get_best(1)

    if not best:
        print("No variants in archive. Run --evolve first.", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(best[0].config, indent=2))


def cmd_explore(args: argparse.Namespace) -> None:
    """Create and output a mutated variant for exploration."""
    from langywrap.hyperagents.archive import Archive
    from langywrap.hyperagents.mutations import mutate

    archive = Archive(get_archive_dir())
    parent = archive.select_parent("fitness_novelty")

    if parent is None:
        print("No variants to mutate. Run --evolve first.", file=sys.stderr)
        sys.exit(1)

    child = mutate(parent, n_mutations=2)
    child.project_origin = args.project or ""
    archive.add(child)

    print(f"Created variant {child.id} (gen {child.generation})")
    print(f"Parent: {child.parent_id}")
    print(f"Mutations: {child.mutations}")
    print(json.dumps(child.config, indent=2))


def cmd_evolve(args: argparse.Namespace) -> None:
    """Run one evolution step (may create seed if archive empty)."""
    from langywrap.hyperagents.archive import Archive
    from langywrap.hyperagents.mutations import mutate

    archive = Archive(get_archive_dir())

    parent = archive.select_parent("fitness_novelty")
    if parent is None:
        # Create seed
        from langywrap.hyperagents.archive import AgentVariant

        seed = AgentVariant(
            generation=0,
            config=_load_current_config(args.project_dir),
            fitness_score=0.5,
            project_origin=args.project or "",
            mutations=["seed"],
        )
        archive.add(seed)
        print(f"Created seed variant {seed.id}")
        return

    child = mutate(parent, n_mutations=int(args.mutations or 1))
    child.project_origin = args.project or ""
    archive.add(child)
    print(f"Evolved: {parent.id} -> {child.id} (gen {child.generation})")
    print(f"Mutations: {child.mutations}")


def cmd_record(args: argparse.Namespace) -> None:
    """Record evaluation metrics for a variant."""
    from langywrap.hyperagents.archive import Archive

    archive = Archive(get_archive_dir())
    metrics = json.loads(args.metrics)
    archive.update_fitness(args.variant_id, metrics)
    variant = archive.get(args.variant_id)
    if variant:
        print(f"Updated {args.variant_id}: fitness={variant.fitness_score:.4f}")
    else:
        print(f"Variant {args.variant_id} not found", file=sys.stderr)


def _load_current_config(project_dir: str | None) -> dict:
    """Load current config from a project's .langywrap/ as seed."""
    if not project_dir:
        return {}
    import yaml

    config = {}
    p = Path(project_dir)
    router_yaml = p / ".langywrap" / "router.yaml"
    if router_yaml.exists():
        config["routes"] = yaml.safe_load(router_yaml.read_text()) or {}
    ralph_yaml = p / ".langywrap" / "ralph.yaml"
    if ralph_yaml.exists():
        rc = yaml.safe_load(ralph_yaml.read_text()) or {}
        config["review_every_n"] = rc.get("review_every_n", 10)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="HyperAgent meta-agent")
    parser.add_argument("--project", "-p", help="Project name for origin tracking")
    parser.add_argument("--project-dir", help="Project directory path")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show archive status")
    sub.add_parser("exploit", help="Output best config")

    explore_p = sub.add_parser("explore", help="Create mutated variant")
    explore_p.add_argument("--project", help="Project origin")

    evolve_p = sub.add_parser("evolve", help="Run one evolution step")
    evolve_p.add_argument("--mutations", "-n", default=1, help="Number of mutations")

    record_p = sub.add_parser("record", help="Record evaluation metrics")
    record_p.add_argument("variant_id", help="Variant ID")
    record_p.add_argument("metrics", help="JSON metrics string")

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "exploit": cmd_exploit,
        "explore": cmd_explore,
        "evolve": cmd_evolve,
        "record": cmd_record,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
