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


def _split_fail_on(values: list[str] | None) -> list[str]:
    """Flatten repeated and newline-separated --fail-on values; blank lines and '#' comments are ignored."""
    conditions = []
    for value in values or []:
        for line in value.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                conditions.append(line)
    return conditions


def _push_results(summary, base_url: str | None) -> None:
    from cortexops import CortexClient
    from cortexops.tracer import _DEFAULT_API_URL, _resolve_api_key, _resolve_api_url

    api_key = _resolve_api_key(None)
    if not api_key:
        print("Warning: --push given but no CORTEXOPS_API_KEY or saved credentials; skipping upload.", file=sys.stderr)
        return
    client = CortexClient(api_key=api_key, base_url=base_url or _resolve_api_url(_DEFAULT_API_URL))
    try:
        project = client.project_for_key()
        if project and project != summary.project:
            print(f"Note: API key is for project '{project}' (dataset says '{summary.project}')")
            summary = summary.model_copy(update={"project": project})
    except Exception:
        pass
    try:
        client.push_eval(summary)
        print(f"Eval pushed to {client.base_url} (run_id={summary.run_id[:8]})")
    except Exception as e:
        print(f"Warning: eval upload failed: {e}", file=sys.stderr)


def cmd_eval_run(args: argparse.Namespace) -> int:
    """cortexops eval run --dataset golden_v1.yaml --agent agent:build_agent() --fail-on 'task_completion < 0.9'

    Exit codes: 0 gate passed, 1 gate failed, 2 configuration error.
    Without --fail-on the gate is 'pass_rate < 1.0', i.e. it fails if any case fails.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from cortexops import EvalSuite
    from cortexops.report import (
        DEFAULT_FAIL_ON,
        append_step_summary,
        build_report,
        gate_passed,
        render_junit,
        render_markdown,
    )

    conditions = _split_fail_on(args.fail_on)
    try:
        for cond in conditions:
            EvalSuite._parse_threshold(cond)
        dataset = EvalSuite._load_dataset(args.dataset)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.project:
        dataset.project = args.project
    if args.judge:
        for case in dataset.cases:
            if case.judge_criteria:
                case.judge = "llm"

    print(f"CortexOps eval\n  dataset : {args.dataset}\n  project : {dataset.project}")
    print(f"  agent   : {args.agent or '(none bound; using passthrough placeholder)'}")
    print(f"  fail-on : {', '.join(conditions) if conditions else DEFAULT_FAIL_ON + ' (default)'}")
    if args.judge:
        judged = sum(1 for c in dataset.cases if c.judge == "llm")
        mode = "LLM" if os.getenv("OPENAI_API_KEY") else "keyword heuristic (OPENAI_API_KEY not set)"
        print(f"  judge   : {mode} on {judged} case(s) with judge_criteria")
    print()

    def passthrough_agent(inp: dict) -> dict:
        """Placeholder — replace with your actual agent import."""
        return {"output": f"[no agent bound] input was: {inp}"}

    try:
        agent = _load_agent(args.agent) if args.agent else passthrough_agent
    except Exception as e:
        print(f"Error: could not load agent '{args.agent}': {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    summary = EvalSuite.run(dataset=dataset, agent=agent, verbose=not args.quiet)
    thresholds = [EvalSuite.evaluate_threshold(summary, c) for c in conditions or [DEFAULT_FAIL_ON]]
    passed = gate_passed(thresholds)

    print()
    for t in thresholds:
        print(f"  {'FAIL' if t.failed else 'ok  '}  {t.expression}  (actual {t.actual:.3f})")

    if args.output:
        Path(args.output).write_text(json.dumps(summary.model_dump(mode="json"), indent=2))
        print(f"\nResults written to {args.output}")
    if args.output_json:
        report = build_report(summary, thresholds, dataset=args.dataset)
        Path(args.output_json).write_text(json.dumps(report, indent=2))
        print(f"JSON report written to {args.output_json}")

    if args.junit_xml:
        Path(args.junit_xml).write_text(render_junit(summary, thresholds))
        print(f"JUnit XML written to {args.junit_xml}")

    markdown = render_markdown(summary, thresholds, dataset=args.dataset, title=args.title)
    if args.summary_md:
        Path(args.summary_md).write_text(markdown)
        print(f"Markdown summary written to {args.summary_md}")
    if not args.no_step_summary and append_step_summary(markdown):
        print("Markdown summary appended to GITHUB_STEP_SUMMARY")

    if args.push:
        _push_results(summary, args.base_url)

    if not passed:
        sys.stdout.flush()
        for t in thresholds:
            if t.failed:
                print(
                    f"\nCI gate FAILED: {t.metric}={t.actual:.3f} {t.op} {t.threshold} (project={summary.project})",
                    file=sys.stderr,
                )
        return 1
    return 0


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

    def sign(v):
        return f"+{v:.1%}" if v >= 0 else f"{v:.1%}"
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




def cmd_dataset_create(args: argparse.Namespace) -> int:
    """cortexops dataset create --name my-dataset --output dataset.yaml"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from cortexops.dataset import GoldenDataset

    ds = GoldenDataset(name=args.name, description=args.description or "")
    ds.save(args.output)
    print(f"Created dataset: {args.output}")
    print("  Add cases by editing the YAML file or using ds.add() in Python.")
    return 0


def cmd_eval_judge(args: argparse.Namespace) -> int:
    """cortexops eval judge --input <str> --output <str> --rubric task_completion"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from cortexops.judge import RUBRICS, LLMJudge

    api_key = args.api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("Error: OPENAI_API_KEY not set. Pass --api-key or set the env var.", file=sys.stderr)
        return 1

    judge = LLMJudge(api_key=api_key, model=args.model or "gpt-4o-mini")
    result = judge.evaluate(
        case_id="cli-eval",
        input=args.input,
        output=args.output,
        rubric=args.rubric or "task_completion",
        expected=args.expected,
    )

    icon = "✓ PASS" if result.passed else "✗ FAIL"
    print(f"\nLLM Judge Result: {icon}")
    rubric_obj   = RUBRICS.get(args.rubric or 'task_completion')
    threshold    = rubric_obj.pass_threshold if rubric_obj else 0.70
    print(f"  Score:     {result.score:.3f} (threshold: {threshold:.2f})")
    print(f"  Model:     {result.model}  ({result.latency_ms}ms)")
    print(f"  Reasoning: {result.reasoning}")
    if args.verbose:
        print(f"  Criteria:  {result.criteria_scores}")

    return 0 if result.passed else 1


def cmd_eval_run_with_judge(args: argparse.Namespace) -> int:
    """cortexops eval run --dataset d.yaml --judge --fail-on task_completion<0.90"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from cortexops.dataset import GoldenDataset

    ds = GoldenDataset.load(args.dataset)
    print("CortexOps eval gate")
    print(f"  dataset : {args.dataset} ({len(ds)} cases)")
    print(f"  project : {args.project or ds.name}")
    if args.fail_on:
        print(f"  fail-on : {args.fail_on}")
    if args.judge:
        print(f"  judge   : LLM-as-judge ({args.model or 'gpt-4o-mini'})")
    print()

    def passthrough_agent(inp):
        return {"output": f"[no agent] input: {inp}"}

    try:
        agent = _load_agent(args.agent) if getattr(args, "agent", None) else passthrough_agent
        result = ds.run(
            agent=agent,
            fail_on=args.fail_on,
            verbose=True,
            use_judge=getattr(args, "judge", False),
            judge_rubric=getattr(args, "rubric", "task_completion"),
            judge_api_key=os.getenv("OPENAI_API_KEY"),
        )
        result.print_report()
        return 0 if result.passed() else 1
    except Exception as e:
        print(f"\nEval failed: {e}", file=sys.stderr)
        return 1



def _load_agent(agent_path: str):
    """Load an agent from 'module:attr' or 'path/to/file.py:attr'.

    The module is imported from the current directory (or PYTHONPATH). `attr` may be a
    dotted path; a trailing '()' calls it with no arguments, for agent factories such as
    'agent:build_agent()'.
    """
    import importlib
    import importlib.util

    if ":" not in agent_path:
        raise ValueError(f"--agent must be 'module:attr' or 'file.py:attr', got '{agent_path}'")
    module_ref, attr = agent_path.rsplit(":", 1)
    attr = attr.strip()
    call = attr.endswith("()")
    if call:
        attr = attr[:-2]
    if not module_ref or not attr:
        raise ValueError(f"--agent must be 'module:attr' or 'file.py:attr', got '{agent_path}'")

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    if module_ref.endswith(".py"):
        file_path = Path(module_ref).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Agent file not found: {module_ref}")
        sys.path.insert(0, str(file_path.parent))
        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot import {module_ref}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[file_path.stem] = module
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_ref)

    obj = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    if call:
        obj = obj()
    if not (callable(obj) or hasattr(obj, "invoke")):
        raise TypeError(f"'{agent_path}' resolved to a non-callable {type(obj).__name__}")
    return obj




def cmd_login(args: argparse.Namespace) -> int:
    """cortexops login"""
    from cortexops.auth import cmd_login as _login
    return _login(
        api_key=getattr(args, 'api_key', None),
        project=getattr(args, 'project', None),
        api_url=getattr(args, 'base_url', 'https://api.getcortexops.com'),
    )


def cmd_logout(args: argparse.Namespace) -> int:
    """cortexops logout"""
    from cortexops.auth import cmd_logout as _logout
    return _logout()


def cmd_whoami(args: argparse.Namespace) -> int:
    """cortexops whoami"""
    from cortexops.auth import cmd_whoami as _whoami
    return _whoami(api_url=getattr(args, 'base_url', None))

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
    run_p.add_argument(
        "--agent", "-a", default=None,
        help="Agent to evaluate: 'module:attr' or 'file.py:attr', imported from the current directory; "
             "append '()' to call a factory, e.g. 'agent:build_agent()'",
    )
    run_p.add_argument(
        "--fail-on", action="append", default=None, metavar="EXPR",
        help="Gate condition, e.g. 'task_completion < 0.90'. Repeatable (or newline-separated); the gate "
             "fails if any is true. Metrics: task_completion, tool_accuracy, pass_rate (0-1). "
             "Default: 'pass_rate < 1.0'",
    )
    run_p.add_argument("--output", "-o", default=None, help="Save the raw EvalSummary JSON (with traces) to file")
    run_p.add_argument("--output-json", default=None, metavar="PATH",
                       help="Save a JSON report (summary, threshold results, gate_passed) to file")
    run_p.add_argument("--summary-md", default=None, metavar="PATH", help="Save a markdown summary to file")
    run_p.add_argument("--junit-xml", default=None, metavar="PATH",
                       help="Save a JUnit XML report (one testcase per eval case and per fail-on condition)")
    run_p.add_argument("--title", default="CortexOps eval gate", help="Heading for the markdown summary")
    run_p.add_argument("--no-step-summary", action="store_true",
                       help="Do not append the markdown summary to $GITHUB_STEP_SUMMARY")
    run_p.add_argument("--judge", action="store_true",
                       help="Score cases that define judge_criteria with the LLM judge (needs OPENAI_API_KEY)")
    run_p.add_argument("--push", action="store_true",
                       help="Upload results to the CortexOps API (needs CORTEXOPS_API_KEY or `cortexops login`)")
    run_p.add_argument("--base-url", default=None, help="CortexOps API URL for --push (default: CORTEXOPS_API_URL)")
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


    # ── login / logout / whoami ───────────────────────────────────────────
    login_p = sub.add_parser("login", help="Save API key to ~/.cortexops/credentials")
    login_p.add_argument("--api-key", default=None, help="cxo-... key (prompted if omitted)")
    login_p.add_argument("--project", "-p", default=None, help="Default project name")
    login_p.add_argument("--base-url", default="https://api.getcortexops.com")

    sub.add_parser("logout", help="Remove stored credentials")
    whoami_p = sub.add_parser("whoami", help="Show current credentials and verify key")
    whoami_p.add_argument("--base-url", default=None)

    # ── version ───────────────────────────────────────────────────────────
    sub.add_parser("version", help="Print version and exit")

    args = parser.parse_args()

    handlers = {
        ("login", None): cmd_login,
        ("logout", None): cmd_logout,
        ("whoami", None): cmd_whoami,
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