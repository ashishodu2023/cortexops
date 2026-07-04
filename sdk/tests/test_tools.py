"""Tool call spans and accuracy."""

from cortexops.models import ToolCall, ToolCallStatus, EvalCase
from cortexops.metrics import ToolAccuracyMetric
from tests.helpers import make_trace


def test_tool_span():
    tc = ToolCall(name="issue_refund", args={"id": "REF-1"}, status=ToolCallStatus.SUCCESS, latency_ms=30)
    assert tc.name == "issue_refund"
    assert tc.status == ToolCallStatus.SUCCESS


def test_tool_calls_aggregated_on_trace():
    trace = make_trace({}, tool_calls=["lookup_refund", "send_email"])
    names = [t.name for t in trace.tool_calls()]
    assert names == ["lookup_refund", "send_email"]
    assert trace.total_tool_calls() == 2


def test_tool_error_status():
    tc = ToolCall(name="pay", status=ToolCallStatus.ERROR, error="timeout")
    assert tc.error == "timeout"
