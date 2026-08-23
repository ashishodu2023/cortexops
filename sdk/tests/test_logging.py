"""Logging does not leak secrets."""

import logging
from unittest.mock import patch

from cortexops import CortexTracer


def test_debug_log_does_not_include_raw_key(caplog, monkeypatch):
    monkeypatch.setenv("CORTEXOPS_API_KEY", "cxo-super-secret-key")
    with caplog.at_level(logging.DEBUG, logger="cortexops.tracer"):
        CortexTracer(project="p", environment="development")
    joined = " ".join(r.message for r in caplog.records)
    assert "cxo-super-secret-key" not in joined


def test_invalid_api_key_logs_actionable_message(caplog):
    tracer = CortexTracer(project="p", api_key="cxo-invalid")

    with patch("httpx.post") as post:
        post.return_value.status_code = 401
        with caplog.at_level(logging.WARNING, logger="cortexops.tracer"):
            tracer.wrap(lambda _: {"ok": True})({})

    assert "Invalid CortexOps API key. Get a free key at getcortexops.com" in caplog.messages
