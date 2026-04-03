"""CortexOps CLI — cortexops <command> [options]

Commands:
  eval run     Run an evaluation suite
  eval diff    Diff two eval runs
  failures     Show recent failures
  traces       List recent traces
  version      Print SDK version
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def cmd_eval_run(args: argparse.Namespace) -> int:
    """cortexops eval run --dataset golden_v1.yaml --project my-agent"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from cortexops import EvalSuite
    from cortexops.eval import EvalThresholdError

    print(f"CortexOps eval\n  dataset : {args.dataset}\n  project : {args.project or 'from dataset'}")
    if args.fail_on:
        print(f"  fail-on : {args.fail_on}")
    print()

    def passthrough_agent(inp: dict) -> dict:
        """Placeholder — replace with your actual agent import."""
        return {"output": f"[no agent bound] input was: {inp}"}

    try:
        agent = _load_agent(args.agent) if args.agent else passthrough_agent
        summary = EvalSuite.run(
            dataset=args.dataset,
            agent=agent,
            verbose=not args.quiet,
            fail_on=args.fail_on,
        )
    except EvalThresholdError as e:
        print(f"\nCI gate FAILED: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(json.dumps(summary.model_dump(mode="json"), indent=2))
        print(f"\nResults written to {args.output}")

    return 0 if summary.failed == 0 else 1


def cmd_eval_diff(args: argparse.Namespace) -> int:
    """cortexops eval diff <run_a> <run_b> --api-key cxo-..."""
    from cortexops import CortexClient

    api_key = args.api_key or os.getenv("CORTEXOPS_API_KEY")
    if not api_key:
        print("Error: --api-key or CORTEXOPS_API_KEY required for diff", file=sys.stderr)
        return 1

    client = CortexClient(api_key=api_key, base_url=args.base_url)
    try:
        diff = client.diff(args.run_a, args.run_b)
    except Exception as e:
        print(f"Error fetching diff: {e}", file=sys.stderr)
        return 1

    delta_tc = diff.get("task_completion_delta", 0)
    delta_tool = diff.get("tool_accuracy_delta", 0)
    regressions = diff.get("regressions", [])
    improvements = diff.get("improvements", [])

    sign = lambda v: f"+{v:.1%}" if v >= 0 else f"{v:.1%}"
    print(f"Diff: {args.run_a[:8]} → {args.run_b[:8]}")
    print(f"  Task completion : {sign(delta_tc)}")
    print(f"  Tool accuracy   : {sign(delta_tool / 100)}")
    if regressions:
        print(f"  Regressions ({len(regressions)}): {', '.join(regressions)}")
    if improvements:
        print(f"  Improvements ({len(improvements)}): {', '.join(improvements)}")

    return 1 if regressions else 0


def cmd_failures(args: argparse.Namespace) -> int:
    """cortexops failures --project my-agent --last 24h"""
    from cortexops import CortexClient

    api_key = args.api_key or os.getenv("CORTEXOPS_API_KEY")
    if not api_key:
        print("Error: --api-key or CORTEXOPS_API_KEY required", file=sys.stderr)
        return 1

    client = CortexClient(api_key=api_key, base_url=args.base_url)
    try:
        traces = client.list_traces(project=args.project, limit=args.limit)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    failed = [t for t in traces if t.get("status") == "failed"]
    if not failed:
        print(f"No failures found for project '{args.project}'")
        return 0

    print(f"Failures — {args.project} (last {len(traces)} traces)")
    print(f"{'Trace ID':<36}  {'Failure kind':<28}  Latency")
    print("-" * 78)
    for t in failed[:args.limit]:
        print(
            f"{t['trace_id']:<36}  {t.get('failure_kind') or 'unknown':<28}  "
            f"{t.get('total_latency_ms', 0):.0f}ms"
        )
    return 0


def cmd_version(_: argparse.Namespace) -> int:
    from cortexops import __version__
    print(f"cortexops {__version__}")
    return 0


def _load_agent(agent_path: str):
    """Load an agent from a dotted path like 'mymodule:my_agent'."""
    if ":" not in agent_path:
        print(f"Error: --agent must be in the format 'module:object', got '{agent_path}'", file=sys.stderr)
        sys.exit(1)
    module_path, attr = agent_path.rsplit(":", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cortexops",
        description="CortexOps — reliability infrastructure for AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    # ── eval ──────────────────────────────────────────────────────────────
    eval_parser = sub.add_parser("eval", help="Evaluation commands")
    eval_sub = eval_parser.add_subparsers(dest="eval_command")

    run_p = eval_sub.add_parser("run", help="Run an eval suite")
    run_p.add_argument("--dataset", "-d", required=True, help="Path to golden dataset YAML")
    run_p.add_argument("--project", "-p", default=None, help="Project name (overrides dataset)")
    run_p.add_argument("--agent", "-a", default=None, help="Agent to evaluate (module:object)")
    run_p.add_argument("--fail-on", default=None, help="e.g. 'task_completion < 0.90'")
    run_p.add_argument("--output", "-o", default=None, help="Save JSON results to file")
    run_p.add_argument("--quiet", "-q", action="store_true", help="Suppress per-case output")

    diff_p = eval_sub.add_parser("diff", help="Diff two eval runs")
    diff_p.add_argument("run_a", help="First run ID")
    diff_p.add_argument("run_b", help="Second run ID")
    diff_p.add_argument("--api-key", default=None)
    diff_p.add_argument("--base-url", default="https://api.cortexops.ai")

    # ── failures ──────────────────────────────────────────────────────────
    fail_p = sub.add_parser("failures", help="List recent agent failures")
    fail_p.add_argument("--project", "-p", required=True)
    fail_p.add_argument("--limit", "-n", type=int, default=20)
    fail_p.add_argument("--api-key", default=None)
    fail_p.add_argument("--base-url", default="https://api.cortexops.ai")

    # ── version ───────────────────────────────────────────────────────────
    sub.add_parser("version", help="Print version and exit")

    args = parser.parse_args()

    handlers = {
        ("eval", "run"): cmd_eval_run,
        ("eval", "diff"): cmd_eval_diff,
        ("failures", None): cmd_failures,
        ("version", None): cmd_version,
    }

    key = (args.command, getattr(args, "eval_command", None))
    handler = handlers.get(key)

    if handler is None:
        parser.print_help()
        sys.exit(0)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
