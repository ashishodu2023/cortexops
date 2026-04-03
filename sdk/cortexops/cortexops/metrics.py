from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from .models import CaseResult, EvalCase, FailureKind, Trace


class Metric(ABC):
    """Base class for all CortexOps eval metrics.
    Subclass this and implement score() to add custom metrics.
    """

    name: str = "base"

    @abstractmethod
    def score(self, case: EvalCase, trace: Trace) -> tuple[float, FailureKind | None, str | None]:
        """Return (score 0-100, failure_kind or None, failure_detail or None)."""


class TaskCompletionMetric(Metric):
    """Checks whether the agent produced a non-empty, non-error output."""

    name = "task_completion"

    def score(self, case: EvalCase, trace: Trace) -> tuple[float, FailureKind | None, str | None]:
        output = trace.output or {}
        output_str = str(output.get("output", output.get("result", output.get("answer", ""))))

        if not output_str or output_str.lower() in ("none", "null", ""):
            return 0.0, FailureKind.UNKNOWN, "Agent produced no output"

        error_patterns = [r"error:", r"exception:", r"traceback", r"failed to"]
        for pat in error_patterns:
            if re.search(pat, output_str, re.IGNORECASE):
                return 20.0, FailureKind.UNKNOWN, f"Output contains error signal: {output_str[:100]}"

        if case.expected_output_contains:
            hits = sum(1 for kw in case.expected_output_contains if kw.lower() in output_str.lower())
            ratio = hits / len(case.expected_output_contains)
            if ratio < 1.0:
                missing = [kw for kw in case.expected_output_contains if kw.lower() not in output_str.lower()]
                return (
                    50.0 + 50.0 * ratio,
                    FailureKind.OUTPUT_FORMAT,
                    f"Missing expected content: {missing}",
                )

        if case.expected_output_not_contains:
            violations = [kw for kw in case.expected_output_not_contains if kw.lower() in output_str.lower()]
            if violations:
                return (
                    30.0,
                    FailureKind.HALLUCINATION,
                    f"Output contains prohibited content: {violations}",
                )

        return 100.0, None, None


class ToolAccuracyMetric(Metric):
    """Checks whether expected tool calls were actually made.

    Looks in two places (in priority order):
    1. Trace node tool_calls (full instrumentation via CortexTracer.record_tool_call)
    2. output['tool_calls_made'] list (lightweight self-reporting from the agent)
    """

    name = "tool_accuracy"

    def score(self, case: EvalCase, trace: Trace) -> tuple[float, FailureKind | None, str | None]:
        if not case.expected_tool_calls:
            return 100.0, None, None

        # Priority 1: instrumented trace nodes
        actual_calls = {tc.name for tc in trace.tool_calls()}

        # Priority 2: agent self-reported via output dict
        if not actual_calls:
            reported = trace.output.get("tool_calls_made", [])
            if isinstance(reported, list):
                actual_calls = set(reported)

        expected = set(case.expected_tool_calls)
        missing = expected - actual_calls

        if not missing:
            return 100.0, None, None

        ratio = len(expected - missing) / len(expected)
        return (
            round(ratio * 100, 1),
            FailureKind.TOOL_CALL_MISMATCH,
            f"Missing tool calls: {sorted(missing)}",
        )


class LatencyMetric(Metric):
    """Checks whether the agent responded within the required latency budget."""

    name = "latency"

    def score(self, case: EvalCase, trace: Trace) -> tuple[float, FailureKind | None, str | None]:
        if case.max_latency_ms is None:
            return 100.0, None, None
        if trace.total_latency_ms <= case.max_latency_ms:
            return 100.0, None, None
        overage = trace.total_latency_ms - case.max_latency_ms
        return (
            max(0.0, 100.0 - (overage / case.max_latency_ms) * 100),
            FailureKind.TIMEOUT,
            f"Latency {trace.total_latency_ms:.0f}ms exceeded budget {case.max_latency_ms:.0f}ms",
        )


class HallucinationMetric(Metric):
    """Detects common hallucination signals in agent output.
    Flags confident fabrications, contradictions, and forbidden facts.
    """

    name = "hallucination"

    HALLUCINATION_PATTERNS = [
        r"\bas of (january|february|march|april|may|june|july|august|september|october|november|december) 20[0-9]{2}\b",
        r"\bi (don't|do not) have (access|information|data)\b",
        r"\bi cannot (access|retrieve|look up)\b",
    ]

    def score(self, case: EvalCase, trace: Trace) -> tuple[float, FailureKind | None, str | None]:
        output = str(trace.output)
        for pat in self.HALLUCINATION_PATTERNS:
            if re.search(pat, output, re.IGNORECASE):
                return (
                    40.0,
                    FailureKind.HALLUCINATION,
                    f"Hallucination signal detected: pattern '{pat}'",
                )
        return 100.0, None, None


def compute_case_result(case: EvalCase, trace: Trace, extra_metrics: "list[Metric] | None" = None) -> CaseResult:
    metrics: list[Metric] = [
        TaskCompletionMetric(),
        ToolAccuracyMetric(),
        LatencyMetric(),
        HallucinationMetric(),
    ]

    if case.judge == "llm":
        from .judge import LLMJudgeMetric
        metrics.append(LLMJudgeMetric())

    if extra_metrics:
        metrics.extend(extra_metrics)

    scores: list[float] = []
    failure_kind: FailureKind | None = None
    failure_detail: str | None = None

    for metric in metrics:
        s, fk, fd = metric.score(case, trace)
        scores.append(s)
        if s < 100.0 and failure_kind is None:
            failure_kind = fk
            failure_detail = fd

    final_score = sum(scores) / len(scores)
    task_ok_score, _, _ = TaskCompletionMetric().score(case, trace)
    tool_score, _, _ = ToolAccuracyMetric().score(case, trace)
    lat_score, _, _ = LatencyMetric().score(case, trace)

    return CaseResult(
        case_id=case.id,
        passed=final_score >= 80.0,
        score=round(final_score, 1),
        task_completion=task_ok_score >= 80.0,
        tool_accuracy=round(tool_score, 1),
        latency_ms=trace.total_latency_ms,
        latency_ok=lat_score >= 80.0,
        failure_kind=failure_kind,
        failure_detail=failure_detail,
        trace=trace,
    )
