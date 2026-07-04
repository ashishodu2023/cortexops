"""Core eval metrics."""

from cortexops.models import EvalCase, FailureKind
from cortexops.metrics import TaskCompletionMetric, ToolAccuracyMetric, LatencyMetric
from tests.helpers import make_trace


def test_task_completion():
    metric = TaskCompletionMetric()
    case = EvalCase(id="c1", input="test", expected_output_contains=["approved", "REF-8821"])
    trace = make_trace({"output": "Refund REF-8821 was approved successfully"})
    score, fk, _ = metric.score(case, trace)
    assert score == 100.0
    assert fk is None


def test_latency_metric():
    metric = LatencyMetric()
    case = EvalCase(id="c1", input="test", max_latency_ms=1000)
    ok, _, _ = metric.score(case, make_trace({}, latency_ms=200))
    bad, fk, _ = metric.score(case, make_trace({}, latency_ms=2000))
    assert ok == 100.0
    assert bad < 100.0
    assert fk == FailureKind.TIMEOUT


def test_tool_accuracy():
    metric = ToolAccuracyMetric()
    case = EvalCase(id="c1", input="test", expected_tool_calls=["lookup_refund", "send_email"])
    score, _, _ = metric.score(case, make_trace({}, tool_calls=["lookup_refund", "send_email"]))
    assert score == 100.0
    partial, fk, fd = metric.score(case, make_trace({}, tool_calls=["lookup_refund"]))
    assert partial == 50.0
    assert fk == FailureKind.TOOL_CALL_MISMATCH
    assert "send_email" in fd
