"""Logging does not leak secrets."""

import logging
from cortexops import CortexTracer


def test_debug_log_does_not_include_raw_key(caplog, monkeypatch):
    monkeypatch.setenv("CORTEXOPS_API_KEY", "cxo-super-secret-key")
    with caplog.at_level(logging.DEBUG, logger="cortexops.tracer"):
        CortexTracer(project="p", environment="development")
    joined = " ".join(r.message for r in caplog.records)
    assert "cxo-super-secret-key" not in joined
