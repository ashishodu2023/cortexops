"""Run the tool_workflows golden dataset as a CI gate.

    pip install cortexops
    python datasets/tool_workflows/run_eval.py                        # reference agent
    python datasets/tool_workflows/run_eval.py --variant flaky_tool   # watch a degraded agent fail
    python datasets/tool_workflows/run_eval.py --fail-on "task_completion < 0.9" --output results.json

Exits 1 when any --fail-on condition is met (default: every case must fully pass).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cortexops import EvalSuite
from cortexops.eval import EvalThresholdError
from workflow_agent import VARIANTS, build_agent

DATASET = Path(__file__).resolve().with_name("golden.yaml")
DEFAULT_FAIL_ON = ["pass_rate < 1.0", "task_completion < 1.0", "tool_accuracy < 1.0"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="reference")
    parser.add_argument("--fail-on", action="append", help=f"repeatable; default: {DEFAULT_FAIL_ON}")
    parser.add_argument("--output", help="write the EvalSummary as JSON")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    summary = EvalSuite.run(DATASET, build_agent(args.variant), verbose=not args.quiet)
    failures = []
    for condition in args.fail_on or DEFAULT_FAIL_ON:
        try:
            EvalSuite._check_threshold(summary, condition)
        except EvalThresholdError as exc:
            failures.append(str(exc))

    if args.output:
        Path(args.output).write_text(json.dumps(summary.model_dump(mode="json"), indent=2))
    if args.quiet:
        print(summary.summary())
    if failures:
        print("\nCI gate FAILED:\n  " + "\n  ".join(failures))
        return 1
    print(f"\nCI gate passed ({summary.passed}/{summary.total_cases} cases, variant={args.variant}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
