"""Sampling configuration."""

import pytest

from cortexops import CortexTracer
from cortexops.models import RunStatus


def _ok(inp: dict) -> dict:
    return {"output": "ok"}


def _boom(inp: dict) -> dict:
    raise RuntimeError("agent exploded")


@pytest.fixture(autouse=True)
def _no_env_rate(monkeypatch):
    monkeypatch.delenv("CORTEXOPS_SAMPLE_RATE", raising=False)


def test_sample_rate_stored():
    t = CortexTracer(project="p", sample_rate=0.25)
    assert t.sample_rate == 0.25
    assert t.sample_errors is True


def test_default_sample_rate_is_one():
    assert CortexTracer(project="p").sample_rate == 1.0


def test_sample_rate_from_env(monkeypatch):
    monkeypatch.setenv("CORTEXOPS_SAMPLE_RATE", "0.1")
    assert CortexTracer(project="p").sample_rate == 0.1


def test_explicit_sample_rate_overrides_env(monkeypatch):
    monkeypatch.setenv("CORTEXOPS_SAMPLE_RATE", "0.1")
    assert CortexTracer(project="p", sample_rate=0.5).sample_rate == 0.5


@pytest.mark.parametrize("value", ["abc", "1.5", "-0.1"])
def test_invalid_env_sample_rate(monkeypatch, value):
    monkeypatch.setenv("CORTEXOPS_SAMPLE_RATE", value)
    with pytest.raises(ValueError):
        CortexTracer(project="p")


def test_unsampled_success_is_dropped():
    t = CortexTracer(project="p", sample_rate=0.0)
    assert t.wrap(_ok)({"q": 1}) == {"output": "ok"}
    assert t.traces() == []


def test_unsampled_error_is_still_captured():
    t = CortexTracer(project="p", sample_rate=0.0)
    t.set_prompt("refund-system", "v2")
    with pytest.raises(RuntimeError, match="agent exploded"):
        t.wrap(_boom)({"q": 1})
    trace = t.last_trace()
    assert trace.status == RunStatus.FAILED
    assert trace.failure_detail == "agent exploded"
    assert trace.metadata == {"sample_rate": 0.0, "sampled": False, "captured_reason": "error"}
    assert trace.prompt_version == "v2"


def test_unsampled_error_is_flushed_when_hosted(monkeypatch):
    sent = []
    t = CortexTracer(project="p", api_key="cxo-test", sample_rate=0.0)
    monkeypatch.setattr(t, "_flush_trace", sent.append)
    with pytest.raises(RuntimeError):
        t.wrap(_boom)({"q": 1})
    assert len(sent) == 1
    assert sent[0].status == RunStatus.FAILED


def test_sample_errors_disabled_drops_errors():
    t = CortexTracer(project="p", sample_rate=0.0, sample_errors=False)
    with pytest.raises(RuntimeError):
        t.wrap(_boom)({"q": 1})
    assert t.traces() == []


def test_sampled_trace_records_rate():
    t = CortexTracer(project="p", sample_rate=1.0)
    t.wrap(_ok)({"q": 1})
    assert t.last_trace().metadata == {"sample_rate": 1.0, "sampled": True}
