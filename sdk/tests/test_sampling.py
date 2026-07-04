"""Sampling configuration."""

from cortexops import CortexTracer


def test_sample_rate_stored():
    t = CortexTracer(project="p", sample_rate=0.25)
    assert t.sample_rate == 0.25
    assert t.sample_errors is True
