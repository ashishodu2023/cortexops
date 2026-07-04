"""Span parent/child relationships and node identity."""

from cortexops.models import TraceNode
from tests.helpers import make_trace


def test_parent_child_relationship():
    parent = TraceNode(node_id="p1", node_name="planner", latency_ms=20)
    child = TraceNode(node_id="c1", node_name="executor", latency_ms=40)
    trace = make_trace(parent_nodes=[parent, child], latency_ms=60)
    ids = {n.node_id for n in trace.nodes}
    assert ids == {"p1", "c1"}
    assert trace.total_latency_ms == 60


def test_span_ids_unique():
    nodes = [TraceNode(node_id=f"n{i}", node_name=f"step_{i}") for i in range(5)]
    trace = make_trace(parent_nodes=nodes)
    assert len({n.node_id for n in trace.nodes}) == 5
