from tests.helpers import make_trace


def test_datadog_span_tags():
    t = make_trace({"output": "ok"}, latency_ms=10)
    tags = [f"project:{t.project}", f"status:{t.status.value}"]
    assert "project:test" in tags
    assert "status:completed" in tags
