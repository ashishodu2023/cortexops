"""Generate the data behind docs/reports/agent-reliability-2026-10.md.

    pip install -e "sdk[pytest]"
    python docs/reports/generate_2026_10.py            # run, print Markdown tables, write the JSON
    python docs/reports/generate_2026_10.py --check    # run and compare with the committed JSON

Runs every open golden dataset in datasets/ against its rule-based reference agent and the four
degraded variants (missing_tool, flaky_tool, injection_susceptible, slow_tool). No LLM, network, or API
key is involved, so every number except latency is identical on every machine. --check compares those
deterministic fields with docs/reports/data/agent-reliability-2026-10.json and exits 1 on any drift.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import cortexops
from cortexops import CortexTracer, EvalSuite
from cortexops.eval import EvalThresholdError

ROOT = Path(__file__).resolve().parents[2]
DATASETS = {
    "customer_support": "support_agent",
    "rag_qa": "rag_agent",
    "tool_workflows": "workflow_agent",
}
VARIANTS = ["reference", "missing_tool", "flaky_tool", "injection_susceptible", "slow_tool"]
GATE = ["pass_rate < 1.0", "task_completion < 1.0", "tool_accuracy < 1.0"]
OUTPUT = Path(__file__).resolve().parent / "data" / "agent-reliability-2026-10.json"
EXCERPT_CHARS = 220
LATENCY_FIELDS = {"latency_p50_ms", "latency_p95_ms", "latency_ms", "environment"}
MEASURED_MS = re.compile(r"Latency \d+ms")


def load_agent_module(dataset: str) -> ModuleType:
    path = ROOT / "datasets" / dataset / f"{DATASETS[dataset]}.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def gate_failures(summary) -> list[str]:
    failures = []
    for condition in GATE:
        try:
            EvalSuite._check_threshold(summary, condition)
        except EvalThresholdError as exc:
            failures.append(str(exc))
    return failures


def excerpt(value) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 3] + "..."


def run_one(dataset: str, module: ModuleType, variant: str, slow_delay_s: float) -> dict:
    tracer = CortexTracer(project=f"report-{dataset}", sample_rate=1.0)
    tracer.api_key = None
    agent = module.build_agent(variant, tracer=tracer, slow_delay_s=slow_delay_s)
    golden = ROOT / "datasets" / dataset / "golden.yaml"
    cases = EvalSuite._load_dataset(golden).cases
    summary = EvalSuite.run(golden, agent, verbose=False)
    traces = tracer.traces()
    assert len(traces) == len(cases), "one agent trace per case"

    flagged = []
    for case, result, trace in zip(cases, summary.case_results, traces, strict=True):
        if result.failure_kind is None:
            continue
        tool_errors = [f"{tc.name}: {tc.error}" for tc in trace.tool_calls() if tc.error]
        if trace.failure_detail:
            tool_errors.append(f"agent raised: {trace.failure_detail}")
        output = (result.trace.output if result.trace else {}) or {}
        flagged.append({
            "case_id": case.id,
            "tags": case.tags,
            "passed": result.passed,
            "score": result.score,
            "failure_kind": result.failure_kind.value,
            "failure_detail": result.failure_detail,
            "latency_ms": round(result.latency_ms, 1),
            "input": excerpt(case.input["input"] if isinstance(case.input, dict) else case.input),
            "output_excerpt": excerpt(output.get("output", "(no output)")),
            "tool_calls_made": output.get("tool_calls_made", []),
            "expected_tool_calls": case.expected_tool_calls,
            "tool_errors": tool_errors,
        })

    kinds = Counter(f["failure_kind"] for f in flagged)
    tags = Counter(t for f in flagged for t in f["tags"])
    failed_gate = gate_failures(summary)
    return {
        "dataset": dataset,
        "variant": variant,
        "variant_description": module.VARIANTS[variant],
        "cases": summary.total_cases,
        "passed": summary.passed,
        "pass_rate": round(summary.passed / summary.total_cases, 4),
        "task_completion_rate": round(summary.task_completion_rate, 4),
        "tool_accuracy": round(summary.tool_accuracy, 2),
        "latency_p50_ms": round(summary.latency_p50_ms, 1),
        "latency_p95_ms": round(summary.latency_p95_ms, 1),
        "latency_breaches": sum(1 for r in summary.case_results if not r.latency_ok),
        "flagged_cases": len(flagged),
        "flagged_but_passed": sum(1 for f in flagged if f["passed"]),
        "failure_kinds": dict(sorted(kinds.items())),
        "flagged_by_tag": dict(sorted(tags.items())),
        "gate": "fail" if failed_gate else "pass",
        "gate_failures": failed_gate,
        "flagged": flagged,
    }


def run_all(slow_delay_s: float) -> dict:
    runs = []
    for dataset in DATASETS:
        module = load_agent_module(dataset)
        for variant in VARIANTS:
            print(f"running {dataset} / {variant} ...", file=sys.stderr)
            runs.append(run_one(dataset, module, variant, slow_delay_s))
    return {
        "report": "agent-reliability-2026-10",
        "kind": "reproducible benchmark on rule-based reference agents; no production data",
        "gate": GATE,
        "slow_delay_s": slow_delay_s,
        "environment": {
            "cortexops": cortexops.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(terse=True),
            "cpu_count": os.cpu_count(),
        },
        "runs": runs,
    }


def strip_latency(value):
    if isinstance(value, dict):
        return {k: strip_latency(v) for k, v in value.items() if k not in LATENCY_FIELDS}
    if isinstance(value, list):
        return [strip_latency(v) for v in value]
    if isinstance(value, str):
        return MEASURED_MS.sub("Latency <measured>ms", value)
    return value


def markdown(data: dict) -> str:
    out = ["| Dataset | Variant | Passed | Task completion | Tool accuracy | Flagged | Flagged but passed "
           "| p50 ms | p95 ms | Gate |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in data["runs"]:
        out.append(
            f"| {r['dataset']} | {r['variant']} | {r['passed']}/{r['cases']} | {r['task_completion_rate']:.1%} "
            f"| {r['tool_accuracy']:.1f} | {r['flagged_cases']} | {r['flagged_but_passed']} "
            f"| {r['latency_p50_ms']:.1f} | {r['latency_p95_ms']:.1f} | {r['gate']} |"
        )
    kinds = sorted({k for r in data["runs"] for k in r["failure_kinds"]})
    out += ["", "| Dataset | Variant | " + " | ".join(kinds) + " |", "|---|---|" + "---|" * len(kinds)]
    for r in data["runs"]:
        if r["flagged_cases"]:
            cells = " | ".join(str(r["failure_kinds"].get(k, 0)) for k in kinds)
            out.append(f"| {r['dataset']} | {r['variant']} | {cells} |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed JSON instead of writing")
    parser.add_argument("--slow-delay", type=float, default=2.0, help="seconds added by the slow_tool variant")
    args = parser.parse_args(argv)
    os.environ.pop("CORTEXOPS_API_KEY", None)

    data = run_all(args.slow_delay)
    print(markdown(data))
    if args.check:
        committed = json.loads(OUTPUT.read_text())
        if strip_latency(committed) != strip_latency(json.loads(json.dumps(data))):
            print(f"\nDRIFT: results differ from {OUTPUT.relative_to(ROOT)}", file=sys.stderr)
            return 1
        print(f"\nOK: deterministic fields match {OUTPUT.relative_to(ROOT)}", file=sys.stderr)
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
