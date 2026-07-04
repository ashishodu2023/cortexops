"""Cost-related fields on traces (latency proxy for MVP)."""

from tests.helpers import make_trace


def test_cost_proxy_latency():
    t = make_trace({"output": "ok"}, latency_ms=250)
    # MVP: cost analytics uses latency + tool count as proxies
    cost_signal = {"latency_ms": t.total_latency_ms, "tool_calls": t.total_tool_calls()}
    assert cost_signal["latency_ms"] == 250
