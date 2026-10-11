"""Logging does not leak secrets."""

import logging
from unittest.mock import patch

import httpx

from cortexops import CortexTracer

INVALID_KEY_MESSAGE = (
    "Invalid CortexOps API key. Get a free key at getcortexops.com "
    "(then set CORTEXOPS_API_KEY or run `cortexops login`). Traces are not being uploaded."
)


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

    assert INVALID_KEY_MESSAGE in caplog.messages


def test_invalid_api_key_warns_once_per_tracer(caplog):
    tracer = CortexTracer(project="p", api_key="cxo-invalid")
    agent = tracer.wrap(lambda _: {"ok": True})

    with patch("httpx.post") as post:
        post.return_value.status_code = 401
        with caplog.at_level(logging.WARNING, logger="cortexops.tracer"):
            agent({})
            agent({})

    assert post.call_count == 2
    assert caplog.messages.count(INVALID_KEY_MESSAGE) == 1


def test_server_error_does_not_log_auth_warning(caplog):
    tracer = CortexTracer(project="p", api_key="cxo-valid")

    with patch("httpx.post") as post:
        post.return_value.status_code = 500
        with caplog.at_level(logging.WARNING, logger="cortexops.tracer"):
            tracer.wrap(lambda _: {"ok": True})({})

    assert INVALID_KEY_MESSAGE not in caplog.messages


def test_upload_exception_does_not_propagate():
    tracer = CortexTracer(project="p", api_key="cxo-valid")

    with patch("httpx.post", side_effect=httpx.ConnectError("boom")):
        result = tracer.wrap(lambda _: {"ok": True})({})

    assert result == {"ok": True}


def test_invalid_api_key_value_never_logged(caplog):
    tracer = CortexTracer(project="p", api_key="cxo-super-secret-key")

    with patch("httpx.post") as post:
        post.return_value.status_code = 401
        with caplog.at_level(logging.DEBUG, logger="cortexops"):
            tracer.wrap(lambda _: {"ok": True})({})

    assert INVALID_KEY_MESSAGE in caplog.messages
    assert "cxo-super-secret-key" not in caplog.text
