#!/bin/bash
# run_real_experiments.sh
#
# One-command script to run real LLM experiments and update paper tables.
#
# Prerequisites:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   pip install masev anthropic
#
# Usage:
#   chmod +x run_real_experiments.sh
#   ./run_real_experiments.sh
#
# This runs: 3 topologies x 10 scenarios x 3 cycles = 90 real API calls
# Estimated cost: ~$0.50-1.00 (Claude Sonnet)
# Estimated time: ~10-15 minutes

set -e

echo "============================================="
echo "MASEV Real Experiment Runner"
echo "============================================="
echo ""

# Check API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set."
    echo "Run: export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

echo "API key found. Starting experiments..."
echo ""

mkdir -p results/real

# Run 30 trials per topology (3 cycles through 10 scenarios)
for topology in star graph tree; do
    echo ""
    echo ">>> Running topology: $topology"
    python -m experiments.run_real_payment_workflow \
        --topology $topology \
        --trials 30 \
        --output results/real/payment_real_${topology}.json
done

echo ""
echo "============================================="
echo "All experiments complete!"
echo "============================================="
echo ""

# Generate summary
python -c "
import json, numpy as np
from pathlib import Path

print('RESULTS SUMMARY')
print('='*60)

for topo in ['star', 'graph', 'tree']:
    f = Path(f'results/real/payment_real_{topo}.json')
    if not f.exists(): continue
    data = json.load(open(f))
    r = data['report']
    n = data['experiment']['n_trials']
    print(f\"\n{topo.upper()} ({n} trials):\")
    print(f\"  Task Success:  {r['task_success_rate']:.2f}\")
    print(f\"  Coordination:  {r['coordination']:.3f}\")
    print(f\"  Communication: {r['communication']:.3f}\")
    print(f\"  Role Adherence:{r['role_adherence']:.3f}\")
    sm = r['sub_metrics']
    print(f\"  MUR:           {sm['message_utility_ratio']:.3f}\")
    print(f\"  Redundancy:    {sm['redundancy_ratio']:.3f}\")
    eb = r['emergent_behaviors']
    top = max(eb.items(), key=lambda x: x[1])
    print(f\"  Top emergent:  {top[0]} = {top[1]:.3f}\")

print()
print('LaTeX table rows (paste into paper.tex):')
print()
print(r'\midrule')
for topo in ['star', 'graph', 'tree']:
    f = Path(f'results/real/payment_real_{topo}.json')
    if not f.exists(): continue
    data = json.load(open(f))
    r = data['report']
    names = {'star':'Centralized (Star)','graph':'Decentralized (Graph)','tree':'Hierarchical (Tree)'}
    print(f\"{names[topo]} & {r['task_success_rate']:.2f} & {r['coordination']:.2f} & {r['communication']:.2f} & {r['role_adherence']:.2f} \\\\\\\\\")
"

echo ""
echo "Done! Copy the LaTeX rows above into your paper."
echo "Results saved in results/real/"
