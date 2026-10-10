"""Prompt version tracking via tracer.set_prompt()."""

import pytest

from cortexops import CortexTracer


def _echo(inp: dict) -> dict:
    return {"output": "ok"}


def test_traces_untagged_by_default(tracer):
    tracer.wrap(_echo)({"q": 1})
    trace = tracer.last_trace()
    assert trace.prompt_name is None
    assert trace.prompt_version is None


def test_set_prompt_tags_subsequent_traces(tracer):
    tracer.set_prompt("refund-system", "v3")
    agent = tracer.wrap(_echo)
    agent({"q": 1})
    agent({"q": 2})
    assert [(t.prompt_name, t.prompt_version) for t in tracer.traces()] == [
        ("refund-system", "v3"),
        ("refund-system", "v3"),
    ]
    assert tracer.prompt == ("refund-system", "v3")


def test_integer_version_is_stringified(tracer):
    tracer.set_prompt("refund-system", 4)
    tracer.wrap(_echo)({"q": 1})
    assert tracer.last_trace().prompt_version == "4"


def test_clear_prompt(tracer):
    tracer.set_prompt("refund-system", "v3")
    tracer.clear_prompt()
    tracer.wrap(_echo)({"q": 1})
    assert tracer.last_trace().prompt_name is None
    assert tracer.prompt is None


def test_use_prompt_restores_previous(tracer):
    tracer.set_prompt("refund-system", "v1")
    agent = tracer.wrap(_echo)
    with tracer.use_prompt("refund-system", "v2-candidate"):
        agent({"q": 1})
    agent({"q": 2})
    versions = [t.prompt_version for t in tracer.traces()]
    assert versions == ["v2-candidate", "v1"]


@pytest.mark.parametrize("name,version", [("", "v1"), ("  ", "v1"), ("p", ""), ("p", "  ")])
def test_set_prompt_rejects_blank(tracer, name, version):
    with pytest.raises(ValueError):
        tracer.set_prompt(name, version)


@pytest.mark.parametrize("name,version", [("p" * 256, "v1"), ("p", "v" * 65)])
def test_set_prompt_rejects_labels_over_api_limits(tracer, name, version):
    with pytest.raises(ValueError, match="at most"):
        tracer.set_prompt(name, version)
    assert tracer.prompt is None


def test_set_prompt_accepts_labels_at_api_limits(tracer):
    tracer.set_prompt("p" * 255, "v" * 64)
    assert tracer.prompt == ("p" * 255, "v" * 64)


def test_async_agno_and_openai_wrappers_are_traced(tracer, monkeypatch):
    import asyncio
    import sys
    import types

    tracer.set_prompt("refund-system", "v3")

    class _Agent:
        def run(self, message, **kwargs):
            return {"output": message}

    fake_agents = types.ModuleType("agents")
    fake_agents.Runner = types.SimpleNamespace(run_sync=lambda agent, prompt, **kw: {"output": prompt})
    monkeypatch.setitem(sys.modules, "agents", fake_agents)

    asyncio.run(tracer._wrap_agno(_Agent()).arun("hi"))
    asyncio.run(tracer._wrap_openai_agents(_Agent()).run("refund #1"))

    traces = tracer.traces()
    assert [t.input for t in traces] == [{"message": "hi"}, {"prompt": "refund #1"}]
    assert {(t.prompt_name, t.prompt_version) for t in traces} == {("refund-system", "v3")}


def test_prompt_and_environment_in_flushed_payload(monkeypatch):
    sent: list[dict] = []
    tracer = CortexTracer(project="p", api_key="cxo-test", environment="production", sample_rate=1.0)
    monkeypatch.setattr(tracer, "_flush_trace", lambda t: sent.append(t.model_dump(mode="json")))
    tracer.set_prompt("refund-system", "v3")
    tracer.wrap(_echo)({"q": 1})
    assert sent[0]["prompt_name"] == "refund-system"
    assert sent[0]["prompt_version"] == "v3"
    assert sent[0]["environment"] == "production"
