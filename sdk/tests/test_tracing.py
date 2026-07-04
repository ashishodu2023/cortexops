"""Tracing: span capture, nested spans, latency."""

from cortexops import CortexTracer, RunStatus, FailureKind
from cortexops.models import TraceNode


def test_span_capture(tracer, echo_agent):
    wrapped = tracer.wrap(echo_agent)
    result = wrapped({"input": "hello"})
    assert "Processed" in str(result)
    trace = tracer.last_trace()
    assert trace is not None
    assert trace.project == "payments-agent"
    assert trace.status == RunStatus.COMPLETED
    assert trace.trace_id


def test_nested_spans(tracer):
    """Parent/child nodes are retained on a single trace."""
    from tests.helpers import make_trace

    parent = TraceNode(node_id="root", node_name="orchestrator", latency_ms=10)
    child = TraceNode(node_id="child", node_name="tool_node", latency_ms=5)
    trace = make_trace(output={"ok": True}, parent_nodes=[parent, child], latency_ms=15)
    assert len(trace.nodes) == 2
    assert trace.nodes[0].node_name == "orchestrator"
    assert trace.nodes[1].node_name == "tool_node"


def test_failure_span(tracer, failing_agent):
    import pytest

    wrapped = tracer.wrap(failing_agent)
    with pytest.raises(RuntimeError):
        wrapped({"input": "boom"})
    trace = tracer.last_trace()
    assert trace.status == RunStatus.FAILED
    assert trace.failure_kind == FailureKind.UNKNOWN


def test_latency_captured(tracer, echo_agent):
    wrapped = tracer.wrap(echo_agent)
    wrapped({"input": "timing"})
    assert tracer.last_trace().total_latency_ms >= 0


def test_clear_resets_traces(tracer, echo_agent):
    wrapped = tracer.wrap(echo_agent)
    wrapped({"input": "a"})
    wrapped({"input": "b"})
    assert len(tracer.traces()) == 2
    tracer.clear()
    assert tracer.traces() == []
    assert tracer.last_trace() is None
