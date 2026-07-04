from tests.helpers import make_trace


def test_honeycomb_event_shape():
    t = make_trace({"output": "ok"}, latency_ms=42)
    event = {
        "name": "cortexops.trace",
        "trace_id": t.trace_id,
        "duration_ms": t.total_latency_ms,
        "project": t.project,
    }
    assert event["duration_ms"] == 42
    assert event["name"] == "cortexops.trace"
