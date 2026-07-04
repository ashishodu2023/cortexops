"""Model serialization round-trip."""

from tests.helpers import make_trace
from cortexops.models import Trace


def test_trace_round_trip():
    original = make_trace({"output": "ok"}, tool_calls=["lookup"], latency_ms=12)
    data = original.model_dump(mode="json")
    restored = Trace.model_validate(data)
    assert restored.trace_id == original.trace_id
    assert restored.total_tool_calls() == 1
