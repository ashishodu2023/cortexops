"""Trace export / serialization for backends."""

from tests.helpers import make_trace


def test_otlp_export():
    """Trace serializes to JSON-ready dict suitable for OTLP-style exporters."""
    payload = make_trace({"output": "ok"}, tool_calls=["lookup"]).model_dump(mode="json")
    assert "trace_id" in payload
    assert "nodes" in payload
    assert payload["nodes"][0]["tool_calls"][0]["name"] == "lookup"
