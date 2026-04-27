"""
experiments/update_paper_with_real_data.py

After running real experiments, this script reads the results
and outputs the exact LaTeX to paste into paper.tex.

Usage:
    python -m experiments.update_paper_with_real_data --results-dir results/real/
"""

from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

def main():
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/real/")

    data = {}
    for topo in ["star", "graph", "tree"]:
        f = results_dir / f"payment_real_{topo}.json"
        if f.exists():
            data[topo] = json.load(open(f))

    if not data:
        print(f"No results found in {results_dir}")
        return

    print("=" * 60)
    print("PAPER UPDATE: Payment Workflow (Real Claude API Data)")
    print("=" * 60)

    # --- Main results row (for Table 2) ---
    # Average across topologies for the "best config" row
    sr = np.mean([d["report"]["task_success_rate"] for d in data.values()])
    c = np.mean([d["report"]["coordination"] for d in data.values()])
    q = np.mean([d["report"]["communication"] for d in data.values()])
    r = np.mean([d["report"]["role_adherence"] for d in data.values()])
    sr_std = np.std([np.mean([t["task_success"] for t in d["trials"]]) for d in data.values()])
    c_std = np.std([d["trial_means"]["coordination"] for d in data.values()])
    q_std = np.std([d["trial_means"]["communication"] for d in data.values()])
    r_std = np.std([d["trial_means"]["role_adherence"] for d in data.values()])

    print("\n--- Table 2: Main Results (Payment Workflow row) ---")
    n_total = sum(d["experiment"]["n_trials"] for d in data.values())
    print(f"Payment Workflow$^\\dagger$ & {sr:.2f}$\\pm${sr_std:.2f} & {c:.2f}$\\pm${c_std:.2f} & {q:.2f}$\\pm${q_std:.2f} & {r:.2f}$\\pm${r_std:.2f} \\\\")
    print(f"% $\\dagger$ = Real Claude Sonnet API calls ({n_total} total trials)")

    # --- Protocol comparison table (for Table 3 or replacement) ---
    print("\n--- Table 3: Protocol Comparison (Real Data) ---")
    topo_names = {"star": "Centralized (Star)", "graph": "Decentralized (Graph)", "tree": "Hierarchical (Tree)"}

    best_sr = max(d["report"]["task_success_rate"] for d in data.values())
    best_c = max(d["report"]["coordination"] for d in data.values())
    best_q = max(d["report"]["communication"] for d in data.values())
    best_r = max(d["report"]["role_adherence"] for d in data.values())

    for topo in ["star", "graph", "tree"]:
        if topo not in data:
            continue
        d = data[topo]["report"]
        vals = []
        for val, best in [(d["task_success_rate"], best_sr), (d["coordination"], best_c),
                          (d["communication"], best_q), (d["role_adherence"], best_r)]:
            s = f"{val:.2f}"
            if abs(val - best) < 0.005:
                s = f"\\textbf{{{s}}}"
            vals.append(s)
        print(f"{topo_names[topo]} & {' & '.join(vals)} \\\\")

    # --- Sub-metrics table ---
    print("\n--- Sub-metrics Breakdown (Real Data) ---")
    for topo in ["star", "graph", "tree"]:
        if topo not in data:
            continue
        sm = data[topo]["report"]["sub_metrics"]
        name = {"star": "Star", "graph": "Graph", "tree": "Tree"}[topo]
        print(f"{name} & {sm['coordination_entropy']:.2f} & {sm['redundancy_ratio']:.2f} & "
              f"{sm['parallelism_index']:.2f} & {sm['message_utility_ratio']:.2f} & "
              f"{sm['information_density']:.2f} & {sm['communication_overhead']:.2f} \\\\")

    # --- Emergent behaviors ---
    print("\n--- Emergent Behaviors (Real Data) ---")
    behavior_names = {
        "free_riding": "Free-Riding",
        "trust_polarization": "Trust Polarization",
        "spontaneous_specialization": "Spont. Specialization",
        "leadership_emergence": "Leadership Emergence",
        "information_hoarding": "Info. Hoarding",
    }
    for bkey, bname in behavior_names.items():
        vals = []
        for topo in ["star", "graph", "tree"]:
            if topo in data:
                v = data[topo]["report"]["emergent_behaviors"][bkey]
                vals.append(f"{v:.2f}")
            else:
                vals.append("--")
        print(f"{bname} & {' & '.join(vals)} \\\\")

    # --- Key observations for prose ---
    print("\n--- Key Observations for Paper Prose ---")
    for topo in ["star", "graph", "tree"]:
        if topo not in data:
            continue
        d = data[topo]
        r = d["report"]
        n = d["experiment"]["n_trials"]
        errors = d["experiment"]["errors"]
        print(f"\n{topo.upper()} ({n} trials, {errors} errors):")
        print(f"  SR={r['task_success_rate']:.2f}, C={r['coordination']:.3f}, Q={r['communication']:.3f}, R={r['role_adherence']:.3f}")
        print(f"  MUR={r['sub_metrics']['message_utility_ratio']:.3f}")
        print(f"  Parallelism={r['sub_metrics']['parallelism_index']:.3f}")
        eb = r["emergent_behaviors"]
        for k, v in sorted(eb.items(), key=lambda x: -x[1]):
            if v > 0.01:
                print(f"  {k}: {v:.3f}")


if __name__ == "__main__":
    main()
