"""Generate test/fixtures/python-parity.json from the Python SDK (the reference implementation).

    cd sdk-js
    pip install -e ../sdk        # or: uv pip install -e ../sdk
    OPENAI_API_KEY= python scripts/gen_parity_fixtures.py

The vitest suite replays every case through the TypeScript port and asserts identical
scores, failure kinds/details, gate decisions and messages.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk"))
sys.path.insert(0, str(ROOT / "examples" / "langgraph_payments"))
os.environ.pop("OPENAI_API_KEY", None)

import yaml  # noqa: E402

from cortexops import EvalSuite  # noqa: E402
from cortexops.eval import EvalThresholdError  # noqa: E402
from cortexops.judge import LLMJudgeMetric, aggregate_usage, format_judge_cost  # noqa: E402
from cortexops.metrics import (  # noqa: E402
    HallucinationMetric,
    LatencyMetric,
    TaskCompletionMetric,
    ToolAccuracyMetric,
    compute_case_result,
)
from cortexops.models import EvalCase, EvalSummary, ToolCall, Trace, TraceNode  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "test" / "fixtures" / "python-parity.json"


def case_result_fields(r) -> dict:
    return {
        "case_id": r.case_id,
        "passed": r.passed,
        "score": r.score,
        "task_completion": r.task_completion,
        "tool_accuracy": r.tool_accuracy,
        "latency_ok": r.latency_ok,
        "failure_kind": r.failure_kind.value if hasattr(r.failure_kind, "value") else r.failure_kind,
        "failure_detail": r.failure_detail,
        "judge_cost_usd": r.judge_cost_usd,
        "judge_tokens_in": r.judge_tokens_in,
        "judge_tokens_out": r.judge_tokens_out,
    }


def metric_fields(score: tuple) -> list:
    s, fk, fd = score
    return [s, fk.value if hasattr(fk, "value") else fk, fd]


def golden_run() -> dict:
    try:
        import langgraph  # noqa: F401
        raise SystemExit("uninstall langgraph: the parity run must use the deterministic FallbackGraph")
    except ImportError:
        pass
    from agent import build_agent

    dataset = yaml.safe_load((ROOT / "examples" / "langgraph_payments" / "golden_v1.yaml").read_text())
    agent = build_agent()
    summary = EvalSuite.run(dataset=dataset, agent=agent, verbose=False)
    return {
        "dataset": "examples/langgraph_payments/golden_v1.yaml",
        "summary": {
            "project": summary.project,
            "dataset_version": summary.dataset_version,
            "total_cases": summary.total_cases,
            "passed": summary.passed,
            "failed": summary.failed,
            "warnings": summary.warnings,
            "task_completion_rate": summary.task_completion_rate,
            "tool_accuracy": summary.tool_accuracy,
        },
        "outputs": {r.case_id: r.trace.output for r in summary.case_results},
        "case_results": [case_result_fields(r) for r in summary.case_results],
    }


# (case kwargs, trace output, tool call names, latency_ms)
METRIC_MATRIX = [
    ({"expected_output_contains": ["approved", "REF-8821"]}, {"output": "Refund REF-8821 was approved successfully"}, [], 100),
    ({"expected_output_contains": ["approved", "REF-8821"]}, {"output": "Refund REF-8821 is pending"}, [], 100),
    ({"expected_output_contains": ["a", "b", "c"]}, {"output": "only a here"}, [], 100),
    ({}, {}, [], 100),
    ({}, {"output": None}, [], 100),
    ({}, {"output": "null"}, [], 100),
    ({}, {"output": "None"}, [], 100),
    ({}, {"output": ""}, [], 100),
    ({}, {"result": "the answer from result"}, [], 100),
    ({}, {"answer": "the answer from answer"}, [], 100),
    ({}, {"output": "Error: upstream exploded"}, [], 100),
    ({}, {"output": "Traceback (most recent call last)"}, [], 100),
    ({}, {"output": "We FAILED TO reach the service " + "x" * 200}, [], 100),
    ({}, {"output": True}, [], 100),
    ({}, {"output": 42}, [], 100),
    ({}, {"output": {"status": "ok", "items": [1, "two", None, False]}}, [], 100),
    ({"expected_output_contains": ["'ok'"]}, {"output": {"status": "ok"}}, [], 100),
    ({"expected_output_not_contains": ["error:", "traceback"]}, {"output": "hello there"}, [], 100),
    ({"expected_output_not_contains": ["refund", "secret"]}, {"output": "Your refund and SECRET code"}, [], 100),
    ({}, {"output": "As of March 2023, rates were low"}, [], 100),
    ({}, {"output": "I don't have access to that"}, [], 100),
    ({}, {"output": "Sorry, I cannot look up orders"}, [], 100),
    ({"expected_tool_calls": ["lookup_refund", "send_email"]}, {"output": "done"}, ["lookup_refund", "send_email"], 100),
    ({"expected_tool_calls": ["lookup_refund", "send_email"]}, {"output": "done"}, ["lookup_refund"], 100),
    ({"expected_tool_calls": ["a", "b", "c"]}, {"output": "done"}, ["a"], 100),
    ({"expected_tool_calls": ["a", "b", "c"]}, {"output": "done"}, ["a", "b"], 100),
    ({"expected_tool_calls": ["c", "b", "a"]}, {"output": "done"}, [], 100),
    ({"expected_tool_calls": ["lookup_refund"]}, {"output": "done", "tool_calls_made": ["lookup_refund"]}, [], 100),
    ({"expected_tool_calls": ["lookup_refund"]}, {"output": "done", "tool_calls_made": ["other"]}, ["x"], 100),
    ({"expected_tool_calls": [f"t{i}" for i in range(16)]}, {"output": "done"}, ["t0"], 100),
    ({"expected_tool_calls": [f"t{i}" for i in range(16)]}, {"output": "done"}, [f"t{i}" for i in range(15)], 100),
    ({"max_latency_ms": 1000}, {"output": "fast"}, [], 200),
    ({"max_latency_ms": 1000}, {"output": "slow"}, [], 1000),
    ({"max_latency_ms": 1000}, {"output": "slow"}, [], 1250.5),
    ({"max_latency_ms": 1000}, {"output": "slow"}, [], 2000),
    ({"max_latency_ms": 1000}, {"output": "very slow"}, [], 5000),
    ({"max_latency_ms": 300}, {"output": "x"}, [], 375),
    ({"judge": "llm", "judge_criteria": "The agent must confirm the refund amount"}, {"output": "Refund confirmed for amount 49.99"}, [], 100),
    ({"judge": "llm", "judge_criteria": "assistance with refunding"}, {"output": "We can assist with refunds"}, [], 100),
    ({"judge": "llm", "judge_criteria": "escalate fraud quickly"}, {"output": "Thanks"}, [], 100),
    ({"judge": "llm", "judge_criteria": "the and of"}, {"output": "anything"}, [], 100),
    ({"judge": "llm"}, {"output": "no criteria"}, [], 100),
    (
        {"expected_tool_calls": ["lookup_refund"], "expected_output_contains": ["approved"], "max_latency_ms": 100},
        {"output": "Error: timeout"},
        [],
        400,
    ),
    ({"expected_output_contains": ["ÜBER"]}, {"output": "über café"}, [], 100),
]


def metric_matrix() -> list:
    out = []
    for i, (case_kwargs, output, tools, latency) in enumerate(METRIC_MATRIX):
        case = EvalCase(id=f"m{i:02d}", input="x", **case_kwargs)
        nodes = [TraceNode(node_id="n1", node_name="agent", tool_calls=[ToolCall(name=n) for n in tools])]
        trace = Trace(project="p", output=output, total_latency_ms=latency, nodes=nodes)
        metrics = {
            "task_completion": metric_fields(TaskCompletionMetric().score(case, trace)),
            "tool_accuracy": metric_fields(ToolAccuracyMetric().score(case, trace)),
            "latency": metric_fields(LatencyMetric().score(case, trace)),
            "hallucination": metric_fields(HallucinationMetric().score(case, trace)),
        }
        if case.judge == "llm":
            metrics["llm_judge"] = metric_fields(LLMJudgeMetric().score(case, trace))
        entry = {"case": case.model_dump(mode="json"), "output": output, "tool_calls": tools,
                 "latency_ms": latency, "metrics": metrics}
        try:
            entry["result"] = case_result_fields(compute_case_result(case, trace))
        except Exception as exc:  # e.g. "llm_judge_heuristic" is not a FailureKind in the Python model
            entry["python_error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        out.append(entry)
    return out


def make_summary(passed: int, total: int, tc_rate: float, tool_acc: float) -> EvalSummary:
    return EvalSummary(
        run_id="00000000-0000-0000-0000-000000000000",
        project="gate-proj",
        dataset_version=1,
        total_cases=total,
        passed=passed,
        failed=total - passed,
        warnings=0,
        task_completion_rate=tc_rate,
        tool_accuracy=tool_acc,
        latency_p50_ms=12.4,
        latency_p95_ms=1999.5,
        timestamp=datetime(2026, 1, 1),
    )


GATE_SUMMARIES = [(9, 10, 0.9, 87.5), (10, 10, 1.0, 100.0), (0, 0, 0.0, 0.0), (7, 9, 0.7777777777777778, 66.66666666666667)]
GATE_EXPRESSIONS = [
    "task_completion < 0.90",
    "task_completion<0.9",
    "task_completion <= 0.9",
    "tool_accuracy < 0.875",
    "tool_accuracy <= .875",
    "pass_rate >= 0.9",
    "pass_rate > 0.5",
    "  task_completion < 1  ",
    "tool_accuracy < 1.0",
]
INVALID_EXPRESSIONS = ["task_completion", "task_completion == 0.9", "latency < 0.9", "pass_rate < abc", "task_completion < -1"]


def gates() -> dict:
    results = []
    for s_args in GATE_SUMMARIES:
        summary = make_summary(*s_args)
        for expr in GATE_EXPRESSIONS:
            try:
                EvalSuite._check_threshold(summary, expr)
                results.append({"summary": list(s_args), "expression": expr, "failed": False, "message": None})
            except EvalThresholdError as e:
                results.append({"summary": list(s_args), "expression": expr, "failed": True, "message": str(e)})
    invalid = []
    for expr in INVALID_EXPRESSIONS:
        try:
            EvalSuite._parse_threshold(expr)
            invalid.append({"expression": expr, "error": None})
        except ValueError as e:
            invalid.append({"expression": expr, "error": str(e)})
    return {"results": results, "invalid": invalid}


def percentiles() -> list:
    out = []
    for n in [1, 2, 3, 9, 10, 19, 20, 21, 100]:
        lat = [float((i * 37) % 101) for i in range(n)]
        s = sorted(lat)
        out.append({"latencies": lat, "p50": s[int(n * 0.50) - 1], "p95": s[int(n * 0.95) - 1]})
    return out


def summary_text() -> dict:
    summary = make_summary(7, 9, 0.7777777777777778, 66.66666666666667)
    summary.case_results = []
    case = EvalCase(id="bad_case", input="x", expected_output_contains=["zzz"])
    trace = Trace(project="p", output={}, total_latency_ms=10)
    summary.case_results.append(compute_case_result(case, trace))
    summary.regressions = 2
    summary.baseline_run_id = "base-123"
    return {"summary": json.loads(summary.model_dump_json(exclude={"case_results": {"__all__": {"trace"}}})), "text": summary.summary()}


# per-case (tokens_in, tokens_out, cost_usd) as reported by the Python LLM judge
JUDGE_USAGES = [
    [],
    [(None, None, None)],
    [(1200, 300, 0.00036)],
    [(1200, 300, 0.00036), (None, None, None), (800, 150, 0.00021)],
    [(1200, 300, 0.00036), (900, 100, None)],
    [(5, None, None)],
    [(0, 0, 0.0)],
    [(1_234_567, 89_012, 0.1), (1, 2, 0.2)],
]
JUDGE_COST_TEXTS = [
    (None, 1200, 300),
    (None, None, 5),
    (0.0, 0, 0),
    (0.00036, 1200, 300),
    (0.005, 3, 4),
    (0.0099999, 10, 1),
    (0.01, 1_234_567, 89_012),
    (12.3456789, 1_000_000, 0),
]


def judge_cost() -> dict:
    summary = make_summary(9, 10, 0.9, 87.5)
    summary.judge_tokens_in, summary.judge_tokens_out, summary.judge_cost_usd = 2_000, 450, 0.00057
    unpriced = make_summary(9, 10, 0.9, 87.5)
    unpriced.judge_tokens_in, unpriced.judge_tokens_out = 2_000, 450
    return {
        "aggregate": [{"usages": [list(u) for u in us], "total": list(aggregate_usage(us))} for us in JUDGE_USAGES],
        "format": [{"args": list(args), "text": format_judge_cost(*args)} for args in JUDGE_COST_TEXTS],
        "summaries": [{"summary": json.loads(s.model_dump_json()), "text": s.summary()} for s in (summary, unpriced)],
    }


def schemas() -> dict:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.models.schemas import CaseResultIngest, EvalSummaryIngest, TraceIngest

    def fields(model) -> dict:
        return {name: {"required": f.is_required(), "type": str(f.annotation)} for name, f in model.model_fields.items()}

    return {
        "sdk_trace": list(Trace.model_fields),
        "sdk_node": list(TraceNode.model_fields),
        "sdk_tool_call": list(ToolCall.model_fields),
        "TraceIngest": fields(TraceIngest),
        "EvalSummaryIngest": fields(EvalSummaryIngest),
        "CaseResultIngest": fields(CaseResultIngest),
    }


def main() -> None:
    data = {
        "generated_by": "sdk-js/scripts/gen_parity_fixtures.py",
        "schemas": schemas(),
        "golden": golden_run(),
        "metric_matrix": metric_matrix(),
        "gates": gates(),
        "percentiles": percentiles(),
        "summary_text": summary_text(),
        "judge_cost": judge_cost(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
