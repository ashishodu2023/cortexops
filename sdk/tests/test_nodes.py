"""Trace node fields."""

from cortexops.models import TraceNode, ToolCall, ToolCallStatus


def test_node_fields():
    node = TraceNode(
        node_id="n1",
        node_name="classify_intent",
        input={"q": "refund"},
        output={"intent": "refund"},
        latency_ms=12.5,
    )
    assert node.node_name == "classify_intent"
    assert node.input["q"] == "refund"
    assert node.latency_ms == 12.5


def test_node_with_tools():
    node = TraceNode(
        node_id="n2",
        node_name="tools",
        tool_calls=[ToolCall(name="lookup_refund", status=ToolCallStatus.SUCCESS)],
    )
    assert node.tool_calls[0].name == "lookup_refund"
