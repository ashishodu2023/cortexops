"""
experiments/run_all.py

Runs all model x topology configurations and generates paper tables.

Usage:
    python -m experiments.run_all --trials 100 --output-dir results/full/

This will run:
  - 3 topologies (star, graph, tree) x N models
  - Generate LaTeX tables for the paper
  - Print summary statistics
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.run_payment_workflow import run_experiment
from experiments.generate_paper_tables import (
    generate_protocol_table,
    generate_submetrics_table,
    generate_emergent_table,
    generate_summary_stats,
    load_results,
)


TOPOLOGIES = ["star", "graph", "tree"]

# Models to test. "simulated" uses the built-in simulator.
# Add real model names when you have API keys configured:
#   "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet"
MODELS = ["simulated"]


def main():
    parser = argparse.ArgumentParser(description="Run all MASEV experiments")
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--output-dir", default="results/full/")
    parser.add_argument("--models", nargs="+", default=MODELS,
                        help="Models to test")
    parser.add_argument("--topologies", nargs="+", default=TOPOLOGIES)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_configs = len(args.models) * len(args.topologies)
    print(f"Running {total_configs} configurations "
          f"({len(args.models)} models x {len(args.topologies)} topologies) "
          f"x {args.trials} trials each")
    print("=" * 60)

    all_results = []
    start = time.time()

    for model in args.models:
        for topology in args.topologies:
            output_path = output_dir / f"payment_{model}_{topology}.json"
            print(f"\n>>> {model} / {topology}")

            result = run_experiment(
                model=model,
                topology=topology,
                n_trials=args.trials,
                output_path=str(output_path),
            )
            all_results.append(result)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"All {total_configs} configurations complete in {elapsed:.1f}s")

    # Generate tables
    print(f"\nGenerating paper tables...")
    results = load_results(str(output_dir))

    tables_path = output_dir / "paper_tables.tex"
    tables = [
        "%" * 60,
        "% AUTO-GENERATED LATEX TABLES",
        "%" * 60,
        "",
        generate_protocol_table(results),
        "",
        generate_submetrics_table(results),
        "",
        generate_emergent_table(results),
        "",
        generate_summary_stats(results),
    ]
    tables_text = "\n".join(tables)

    with open(tables_path, "w") as f:
        f.write(tables_text)

    print(tables_text)
    print(f"\nTables saved to {tables_path}")


if __name__ == "__main__":
    main()
