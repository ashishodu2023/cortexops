"""Tests for CortexOps SDK — tracer, eval, and metrics."""

import pytest

from cortexops import (
    CortexTracer,
    EvalSuite,
    EvalThresholdError,
    FailureKind,
    RunStatus,
)
from cortexops.models import EvalCase, EvalDataset, Trace, TraceNode, ToolCall, ToolCallStatus
from cortexops.metrics import TaskCompletionMetric, ToolAccuracyMetric, LatencyMetric


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_trace(output: dict, tool_calls: list[str] | None = None, latency_ms: float = 100.0) -> Trace:
    tcs = [ToolCall(name=n, status=ToolCallStatus.SUCCESS) for n in (tool_calls or [])]
    node = TraceNode(node_id="n1", node_name="agent", output=output, tool_calls=tcs, latency_ms=latency_ms)
    return Trace(project="test", total_latency_ms=latency_ms, output=output, nodes=[node], status=RunStatus.COMPLETED)


def echo_agent(input: dict) -> dict:
    return {"output": f"Processed: {input.get('input', '')}"}


def failing_agent(input: dict) -> dict:
    raise RuntimeError("agent exploded")


# ---------------------------------------------------------------------------
# CortexTracer
# ---------------------------------------------------------------------------

class TestCortexTracer:
    def test_wraps_callable_and_records_trace(self):
        tracer = CortexTracer(project="test")
        wrapped = tracer.wrap(echo_agent)
        result = wrapped({"input": "hello"})
        assert "Processed" in str(result)
        trace = tracer.last_trace()
        assert trace is not None
        assert trace.project == "test"
        assert trace.status == RunStatus.COMPLETED

    def test_records_failure_on_exception(self):
        tracer = CortexTracer(project="test")
        wrapped = tracer.wrap(failing_agent)
        with pytest.raises(RuntimeError):
            wrapped({"input": "boom"})
        trace = tracer.last_trace()
        assert trace.status == RunStatus.FAILED
        assert trace.failure_kind == FailureKind.UNKNOWN

    def test_latency_is_captured(self):
        tracer = CortexTracer(project="test")
        wrapped = tracer.wrap(echo_agent)
        wrapped({"input": "timing"})
        trace = tracer.last_trace()
        assert trace.total_latency_ms >= 0

    def test_clear_resets_traces(self):
        tracer = CortexTracer(project="test")
        wrapped = tracer.wrap(echo_agent)
        wrapped({"input": "a"})
        wrapped({"input": "b"})
        assert len(tracer.traces()) == 2
        tracer.clear()
        assert len(tracer.traces()) == 0
        assert tracer.last_trace() is None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestTaskCompletionMetric:
    metric = TaskCompletionMetric()

    def test_passes_with_output(self):
        case = EvalCase(id="c1", input="test")
        trace = make_trace({"output": "the refund was approved"})
        score, fk, _ = self.metric.score(case, trace)
        assert score == 100.0
        assert fk is None

    def test_fails_empty_output(self):
        case = EvalCase(id="c1", input="test")
        trace = make_trace({"output": ""})
        score, fk, _ = self.metric.score(case, trace)
        assert score == 0.0

    def test_partial_score_missing_keywords(self):
        case = EvalCase(id="c1", input="test", expected_output_contains=["approved", "REF-8821"])
        trace = make_trace({"output": "The refund was approved"})
        score, fk, _ = self.metric.score(case, trace)
        assert 50.0 <= score < 100.0
        assert fk == FailureKind.OUTPUT_FORMAT

    def test_full_score_all_keywords_present(self):
        case = EvalCase(id="c1", input="test", expected_output_contains=["approved", "REF-8821"])
        trace = make_trace({"output": "Refund REF-8821 was approved successfully"})
        score, fk, _ = self.metric.score(case, trace)
        assert score == 100.0


class TestToolAccuracyMetric:
    metric = ToolAccuracyMetric()

    def test_no_expected_tools_is_perfect(self):
        case = EvalCase(id="c1", input="test")
        trace = make_trace({})
        score, _, _ = self.metric.score(case, trace)
        assert score == 100.0

    def test_all_tools_called(self):
        case = EvalCase(id="c1", input="test", expected_tool_calls=["lookup_refund", "send_email"])
        trace = make_trace({}, tool_calls=["lookup_refund", "send_email"])
        score, _, _ = self.metric.score(case, trace)
        assert score == 100.0

    def test_missing_tool_reduces_score(self):
        case = EvalCase(id="c1", input="test", expected_tool_calls=["lookup_refund", "send_email"])
        trace = make_trace({}, tool_calls=["lookup_refund"])
        score, fk, fd = self.metric.score(case, trace)
        assert score == 50.0
        assert fk == FailureKind.TOOL_CALL_MISMATCH
        assert "send_email" in fd


class TestLatencyMetric:
    metric = LatencyMetric()

    def test_within_budget(self):
        case = EvalCase(id="c1", input="test", max_latency_ms=2000)
        trace = make_trace({}, latency_ms=800)
        score, _, _ = self.metric.score(case, trace)
        assert score == 100.0

    def test_over_budget(self):
        case = EvalCase(id="c1", input="test", max_latency_ms=1000)
        trace = make_trace({}, latency_ms=2000)
        score, fk, _ = self.metric.score(case, trace)
        assert score < 100.0
        assert fk == FailureKind.TIMEOUT

    def test_no_budget_always_passes(self):
        case = EvalCase(id="c1", input="test")
        trace = make_trace({}, latency_ms=99999)
        score, _, _ = self.metric.score(case, trace)
        assert score == 100.0


# ---------------------------------------------------------------------------
# EvalSuite
# ---------------------------------------------------------------------------

class TestEvalSuite:
    def _make_dataset(self) -> EvalDataset:
        return EvalDataset(
            version=1,
            project="test-agent",
            cases=[
                EvalCase(id="case_01", input="What is 2+2?", expected_output_contains=["4"]),
                EvalCase(id="case_02", input="Say hello", expected_output_contains=["hello"]),
            ],
        )

    def test_run_passes_with_matching_agent(self):
        def smart_agent(inp: dict) -> dict:
            q = inp.get("input", "")
            if "2+2" in q:
                return {"output": "The answer is 4"}
            return {"output": "hello there"}

        ds = self._make_dataset()
        summary = EvalSuite.run(dataset=ds, agent=smart_agent, verbose=False)
        assert summary.total_cases == 2
        assert summary.passed == 2
        assert summary.task_completion_rate == 1.0

    def test_run_detects_failures(self):
        def dumb_agent(inp: dict) -> dict:
            return {"output": "I don't know"}

        ds = self._make_dataset()
        summary = EvalSuite.run(dataset=ds, agent=dumb_agent, verbose=False)
        # task_completion should be 0 — agent never produced expected keywords
        assert summary.task_completion_rate == 0.0

    def test_fail_on_threshold_raises(self):
        def bad_agent(inp: dict) -> dict:
            return {"output": "nothing useful"}

        ds = self._make_dataset()
        with pytest.raises(EvalThresholdError):
            # task_completion will be 0.0 < 0.5 → CI gate fires
            EvalSuite.run(dataset=ds, agent=bad_agent, verbose=False, fail_on="task_completion < 0.5")

    def test_summary_string_renders(self):
        def agent(inp: dict) -> dict:
            return {"output": inp.get("input", "")}

        ds = self._make_dataset()
        summary = EvalSuite.run(dataset=ds, agent=agent, verbose=False)
        text = summary.summary()
        assert "test-agent" in text
        assert "Task completion" in text
