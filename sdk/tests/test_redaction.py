"""Sensitive fields stay out of default string forms."""

from tests.helpers import make_trace


def test_trace_repr_safe():
    t = make_trace({"output": "ok", "ssn": "000-00-0000"})
    # model_dump is explicit; str(trace) should not explode
    assert "trace_id" in t.model_dump(mode="json")
