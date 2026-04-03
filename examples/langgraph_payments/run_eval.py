"""
CortexOps — run evals against the payments agent
=================================================

Usage:
    cd examples/langgraph_payments
    pip install -e ../../sdk
    python run_eval.py

    # With CI threshold (exits non-zero if eval fails):
    python run_eval.py --fail-on "task_completion < 0.90"

    # Save results to JSON:
    python run_eval.py --output results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from cortexops import CortexTracer, EvalSuite
from cortexops.eval import EvalThresholdError
from agent import build_agent


def main():
    parser = argparse.ArgumentParser(description="Run CortexOps evals for the payments agent")
    parser.add_argument("--dataset", default="golden_v1.yaml", help="Path to golden dataset YAML")
    parser.add_argument("--fail-on", default=None, help="e.g. 'task_completion < 0.90'")
    parser.add_argument("--output", default=None, help="Save JSON summary to this path")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-case output")
    args = parser.parse_args()

    print("CortexOps eval runner")
    print(f"  Dataset  : {args.dataset}")
    print(f"  Fail on  : {args.fail_on or 'none'}")
    print()

    tracer = CortexTracer(project="payments-agent")
    agent = tracer.wrap(build_agent())

    def instrumented_agent(inp: dict) -> dict:
        return agent.invoke(inp)

    try:
        summary = EvalSuite.run(
            dataset=args.dataset,
            agent=instrumented_agent,
            verbose=not args.quiet,
            fail_on=args.fail_on,
        )
    except EvalThresholdError as e:
        print(f"\nCI gate FAILED: {e}")
        sys.exit(1)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(summary.model_dump(mode="json"), indent=2))
        print(f"\nResults written to {out_path}")

    exit_code = 0 if summary.failed == 0 else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
