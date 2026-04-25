"""
experiments/generate_paper_tables.py

Reads all experiment result JSONs and generates LaTeX tables
ready to paste into the NeurIPS paper.

Usage:
    python -m experiments.generate_paper_tables --results-dir results/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def load_results(results_dir: str) -> list[dict]:
    """Load all result JSONs from directory."""
    results = []
    for f in sorted(Path(results_dir).glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
            data["_file"] = f.name
            results.append(data)
    return results


def generate_protocol_table(results: list[dict]) -> str:
    """Generate Table 3: Protocol comparison (payment workflow)."""
    lines = [
        r"\begin{table}[t]",
        r"\caption{Impact of coordination protocol on \framework{} dimensions (Payment Workflow, 100 trials per protocol).}",
        r"\label{tab:protocol}",
        r"\centering",
        r"\begin{tabular}{@{}lcccc@{}}",
        r"\toprule",
        r"\textbf{Protocol} & \textbf{SR} & $\mathcal{C}$ & $\mathcal{Q}$ & $\mathcal{R}$ \\",
        r"\midrule",
    ]

    topology_names = {
        "star": "Centralized (Star)",
        "graph": "Decentralized (Graph)",
        "tree": "Hierarchical (Tree)",
    }

    rows = {}
    for r in results:
        topo = r["experiment"]["topology"]
        rpt = r["report"]
        rows[topo] = {
            "sr": rpt["task_success_rate"],
            "c": rpt["coordination"],
            "q": rpt["communication"],
            "r": rpt["role_adherence"],
        }

    # Find best per column for bolding
    best = {
        "sr": max(rows.values(), key=lambda x: x["sr"])["sr"],
        "c": max(rows.values(), key=lambda x: x["c"])["c"],
        "q": max(rows.values(), key=lambda x: x["q"])["q"],
        "r": max(rows.values(), key=lambda x: x["r"])["r"],
    }

    for topo in ["star", "graph", "tree"]:
        if topo not in rows:
            continue
        r = rows[topo]
        name = topology_names.get(topo, topo)
        vals = []
        for key in ["sr", "c", "q", "r"]:
            v = r[key]
            s = f"{v:.2f}"
            if abs(v - best[key]) < 0.001:
                s = r"\textbf{" + s + "}"
            vals.append(s)
        lines.append(f"{name} & {' & '.join(vals)} \\\\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    return "\n".join(lines)


def generate_submetrics_table(results: list[dict]) -> str:
    """Generate detailed sub-metrics table."""
    lines = [
        r"\begin{table}[t]",
        r"\caption{Sub-metric breakdown by protocol (Payment Workflow).}",
        r"\label{tab:submetrics}",
        r"\centering",
        r"\begin{tabular}{@{}lcccccc@{}}",
        r"\toprule",
        r"\textbf{Protocol} & \textbf{Entropy} & \textbf{Redund.} & \textbf{Parallel.} & \textbf{MUR} & \textbf{Density} & \textbf{Overhead} \\",
        r"\midrule",
    ]

    topology_names = {
        "star": "Star",
        "graph": "Graph",
        "tree": "Tree",
    }

    for r in results:
        topo = r["experiment"]["topology"]
        name = topology_names.get(topo, topo)
        sm = r["report"]["sub_metrics"]
        vals = [
            f"{sm['coordination_entropy']:.2f}",
            f"{sm['redundancy_ratio']:.2f}",
            f"{sm['parallelism_index']:.2f}",
            f"{sm['message_utility_ratio']:.2f}",
            f"{sm['information_density']:.2f}",
            f"{sm['communication_overhead']:.2f}",
        ]
        lines.append(f"{name} & {' & '.join(vals)} \\\\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    return "\n".join(lines)


def generate_emergent_table(results: list[dict]) -> str:
    """Generate emergent behavior table."""
    lines = [
        r"\begin{table}[t]",
        r"\caption{Emergent behaviors detected in Payment Workflow (100 trials per protocol).}",
        r"\label{tab:emergent_payment}",
        r"\centering",
        r"\begin{tabular}{@{}lccc@{}}",
        r"\toprule",
        r"\textbf{Behavior} & \textbf{Star} & \textbf{Graph} & \textbf{Tree} \\",
        r"\midrule",
    ]

    behavior_names = {
        "free_riding": "Free-Riding",
        "trust_polarization": "Trust Polarization",
        "spontaneous_specialization": "Spont. Specialization",
        "leadership_emergence": "Leadership Emergence",
        "information_hoarding": "Info. Hoarding",
    }

    # Collect by topology
    by_topo = {}
    for r in results:
        by_topo[r["experiment"]["topology"]] = r["report"]["emergent_behaviors"]

    for bkey, bname in behavior_names.items():
        vals = []
        for topo in ["star", "graph", "tree"]:
            if topo in by_topo:
                v = by_topo[topo].get(bkey, 0.0)
                s = f"{v:.2f}"
                # Bold the highest
                all_vals = [by_topo.get(t, {}).get(bkey, 0) for t in ["star", "graph", "tree"]]
                if abs(v - max(all_vals)) < 0.001 and v > 0.01:
                    s = r"\textbf{" + s + "}"
                vals.append(s)
            else:
                vals.append("--")
        lines.append(f"{bname} & {' & '.join(vals)} \\\\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    return "\n".join(lines)


def generate_summary_stats(results: list[dict]) -> str:
    """Generate text summary of key findings."""
    lines = ["", "=" * 60, "KEY FINDINGS FOR PAPER", "=" * 60, ""]

    for r in results:
        topo = r["experiment"]["topology"]
        rpt = r["report"]
        lines.append(f"--- {topo.upper()} topology ---")
        lines.append(f"  Task Success Rate: {rpt['task_success_rate']:.3f}")
        lines.append(f"  Coordination:      {rpt['coordination']:.3f}")
        lines.append(f"  Communication:     {rpt['communication']:.3f}")
        lines.append(f"  Role Adherence:    {rpt['role_adherence']:.3f}")
        lines.append(f"  MUR:               {rpt['sub_metrics']['message_utility_ratio']:.3f}")
        lines.append(f"  Parallelism:       {rpt['sub_metrics']['parallelism_index']:.3f}")
        eb = rpt["emergent_behaviors"]
        top_emergent = max(eb.items(), key=lambda x: x[1])
        lines.append(f"  Top emergent:      {top_emergent[0]} = {top_emergent[1]:.3f}")
        lines.append("")

    # Cross-topology observations
    topos = {r["experiment"]["topology"]: r["report"] for r in results}
    if "star" in topos and "graph" in topos:
        lines.append("CROSS-TOPOLOGY OBSERVATIONS:")
        sr_diff = topos["star"]["task_success_rate"] - topos["graph"]["task_success_rate"]
        c_diff = topos["graph"]["coordination"] - topos["star"]["coordination"]
        q_diff = topos["star"]["communication"] - topos["graph"]["communication"]
        lines.append(f"  Graph has {c_diff:+.3f} coordination vs star")
        lines.append(f"  Star has {q_diff:+.3f} communication vs graph")
        lines.append(f"  SR difference: {sr_diff:+.3f}")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="results/")
    parser.add_argument("--output", default=None, help="Save tables to file")
    args = parser.parse_args()

    results = load_results(args.results_dir)
    if not results:
        print(f"No results found in {args.results_dir}")
        return

    print(f"Loaded {len(results)} result files")

    # Generate all tables
    protocol_table = generate_protocol_table(results)
    submetrics_table = generate_submetrics_table(results)
    emergent_table = generate_emergent_table(results)
    summary = generate_summary_stats(results)

    output_lines = [
        "%" * 60,
        "% AUTO-GENERATED LATEX TABLES FROM MASEV EXPERIMENTS",
        "% Paste these into your NeurIPS paper",
        "%" * 60,
        "",
        "% Table: Protocol Comparison",
        protocol_table,
        "",
        "% Table: Sub-metric Breakdown",
        submetrics_table,
        "",
        "% Table: Emergent Behaviors",
        emergent_table,
        "",
        summary,
    ]

    full_output = "\n".join(output_lines)
    print(full_output)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(full_output)
        print(f"\nTables saved to {args.output}")


if __name__ == "__main__":
    main()
