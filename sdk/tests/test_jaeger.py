from tests.helpers import make_trace


def test_jaeger_span_refs():
    t = make_trace({"output": "ok"}, parent_nodes=[
        __import__("cortexops.models", fromlist=["TraceNode"]).TraceNode(node_id="a", node_name="root"),
        __import__("cortexops.models", fromlist=["TraceNode"]).TraceNode(node_id="b", node_name="child"),
    ])
    assert len(t.nodes) == 2
