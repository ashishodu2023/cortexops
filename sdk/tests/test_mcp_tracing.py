"""MCP tool-call tracing against a fake ClientSession (no `mcp` package required)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from cortexops import CortexTracer
from cortexops.integrations.mcp import (
    MCPToolError,
    instrument_mcp_session,
    mcp_node,
    trace_run,
    truncate_value,
    uninstrument_mcp_session,
)
from cortexops.models import FailureKind, RunStatus, ToolCallStatus


def _text_result(text: str, *, is_error: bool = False, v2: bool = True, structured=None):
    block = SimpleNamespace(type="text", text=text)
    if v2:
        return SimpleNamespace(content=[block], is_error=is_error, structured_content=structured)
    return SimpleNamespace(content=[block], isError=is_error, structuredContent=structured)


class FakeSession:
    def __init__(self, delay: float = 0.0) -> None:
        self.calls: list[tuple[str, dict | None]] = []
        self.delay = delay

    async def call_tool(self, name, arguments=None, read_timeout_seconds=None, progress_callback=None, **kwargs):
        self.calls.append((name, arguments))
        if self.delay:
            await asyncio.sleep(self.delay)
        if name == "explode":
            raise ConnectionError("server went away")
        if name == "slow":
            raise TimeoutError("timed out")
        if name == "bad":
            return _text_result("issue 999 not found", is_error=True)
        if name == "legacy":
            return _text_result("ok", v2=False)
        if name == "structured":
            return _text_result('{"n": 3}', structured={"n": 3})
        return _text_result(f"{name} ok")

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name="search"), SimpleNamespace(name="fetch")])


@pytest.fixture
def tracer():
    return CortexTracer(project="mcp-test", sample_rate=1.0)


def _run(coro):
    return asyncio.run(coro)


def test_call_inside_trace_run_creates_node_with_tool_call(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="github")

    async def agent():
        async with trace_run(tracer, input={"task": "triage"}) as trace:
            result = await session.call_tool("get_issue", {"number": 42})
            trace.output = {"answer": "done"}
        return result

    result = _run(agent())
    assert result.content[0].text == "get_issue ok"
    trace = tracer.last_trace()
    assert trace.status == RunStatus.COMPLETED
    assert trace.output == {"answer": "done"}
    assert trace.metadata["framework"] == "mcp"
    assert [n.node_name for n in trace.nodes] == ["mcp:github/get_issue"]
    node = trace.nodes[0]
    assert node.input["server"] == "github"
    tc = node.tool_calls[0]
    assert tc.name == "github/get_issue"
    assert tc.args == {"number": 42}
    assert tc.result == "get_issue ok"
    assert tc.status == ToolCallStatus.SUCCESS
    assert tc.latency_ms >= 0
    assert trace.tool_calls() == [tc]


def test_is_error_result_recorded_as_error_without_raising(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="github")

    async def agent():
        async with trace_run(tracer):
            return await session.call_tool("bad", {"number": 999})

    result = _run(agent())
    assert result.is_error is True
    trace = tracer.last_trace()
    tc = trace.tool_calls()[0]
    assert tc.status == ToolCallStatus.ERROR
    assert tc.error == "issue 999 not found"
    assert tc.result is None
    assert trace.status == RunStatus.COMPLETED
    assert trace.metadata["mcp_tool_errors"] == 1


def test_raise_on_error_fails_run_with_tool_error_kind(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="github", raise_on_error=True)

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("bad", {})

    with pytest.raises(MCPToolError, match="issue 999 not found"):
        _run(agent())
    trace = tracer.last_trace()
    assert trace.status == RunStatus.FAILED
    assert trace.failure_kind == FailureKind.TOOL_ERROR
    assert "'bad' returned an error" in trace.failure_detail


def test_exception_recorded_and_reraised_with_tool_error_kind(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="svc")

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("explode", {"x": 1})

    with pytest.raises(ConnectionError):
        _run(agent())
    trace = tracer.last_trace()
    tc = trace.tool_calls()[0]
    assert tc.status == ToolCallStatus.ERROR
    assert tc.error == "ConnectionError: server went away"
    assert trace.failure_kind == FailureKind.TOOL_ERROR


def test_wrapped_exception_still_classified_as_tool_error(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="svc")

    async def agent():
        async with trace_run(tracer):
            try:
                await session.call_tool("explode", {})
            except ConnectionError as exc:
                raise RuntimeError("agent gave up") from exc

    with pytest.raises(RuntimeError):
        _run(agent())
    assert tracer.last_trace().failure_kind == FailureKind.TOOL_ERROR


def test_timeout_classified(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="svc")

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("slow", {})

    with pytest.raises(TimeoutError):
        _run(agent())
    trace = tracer.last_trace()
    assert trace.tool_calls()[0].status == ToolCallStatus.TIMEOUT
    assert trace.failure_kind == FailureKind.TIMEOUT


def test_non_tool_exception_is_unknown(tracer):
    session = instrument_mcp_session(FakeSession(), tracer)

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("search", {})
            raise ValueError("model returned garbage")

    with pytest.raises(ValueError):
        _run(agent())
    trace = tracer.last_trace()
    assert trace.failure_kind == FailureKind.UNKNOWN
    assert trace.failure_detail == "model returned garbage"


def test_mcp_1x_camelcase_result_fields(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="s")

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("legacy", {})
            await session.call_tool("structured", {})

    _run(agent())
    calls = tracer.last_trace().tool_calls()
    assert calls[0].result == "ok"
    assert calls[1].result == {"n": 3}


def test_no_active_trace_is_noop_but_callback_fires(tracer):
    seen = []
    session = instrument_mcp_session(FakeSession(), tracer, server_name="s", on_tool_call=seen.append)
    result = _run(session.call_tool("search", {"q": "x"}))
    assert result.content[0].text == "search ok"
    assert tracer.traces() == []
    assert [tc.name for tc in seen] == ["s/search"]


def test_finished_sync_run_is_not_reused(tracer):
    wrapped = tracer.wrap(lambda inp: {"ok": True})
    wrapped({"q": 1})
    finished = tracer.last_trace()
    session = instrument_mcp_session(FakeSession(), tracer, server_name="s")
    _run(session.call_tool("search", {}))
    assert finished.nodes == []


def test_mcp_node_groups_calls(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="web")

    async def agent():
        async with trace_run(tracer):
            async with mcp_node(tracer, "research") as node:
                await session.call_tool("search", {"q": "refunds"})
                await session.call_tool("fetch", {"url": "https://example.com"})
                node.output = {"sources": 2}
            await session.call_tool("summarize", {})

    _run(agent())
    trace = tracer.last_trace()
    assert [n.node_name for n in trace.nodes] == ["research", "mcp:web/summarize"]
    research = trace.nodes[0]
    assert [tc.name for tc in research.tool_calls] == ["web/search", "web/fetch"]
    assert research.output == {"sources": 2}


def test_concurrent_runs_do_not_mix_calls(tracer):
    session = instrument_mcp_session(FakeSession(delay=0.01), tracer, server_name="s")

    async def one(label: str):
        async with trace_run(tracer, input={"label": label}):
            await session.call_tool(f"a_{label}", {})
            await session.call_tool(f"b_{label}", {})

    async def main():
        await asyncio.gather(one("x"), one("y"))

    _run(main())
    by_label = {t.input["label"]: [tc.name for tc in t.tool_calls()] for t in tracer.traces()}
    assert by_label == {"x": ["s/a_x", "s/b_x"], "y": ["s/a_y", "s/b_y"]}


def test_sync_trace_run_with_record_tool_call(tracer):
    with trace_run(tracer, input={"q": 1}) as trace:
        with tracer.trace_node("plan"):
            pass
        tracer.record_tool_call("lookup", {"id": 1})
    assert tracer.last_trace() is trace
    assert trace.tool_calls()[0].name == "lookup"


def test_prompt_version_tagged(tracer):
    tracer.set_prompt("refund-system", "v3")
    session = instrument_mcp_session(FakeSession(), tracer)

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("search", {})

    _run(agent())
    trace = tracer.last_trace()
    assert (trace.prompt_name, trace.prompt_version) == ("refund-system", "v3")


def test_secret_args_redacted_and_large_values_truncated(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, max_value_chars=20)

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("search", {
                "query": "x" * 100,
                "api_key": "sk-live-123",
                "headers": {"Authorization": "Bearer abc", "X-Api-Key": "k"},
                "access_token": "t",
                "max_tokens": 50,
            })

    _run(agent())
    args = tracer.last_trace().tool_calls()[0].args
    assert args["query"].startswith("x" * 20) and "truncated 80 chars" in args["query"]
    assert args["api_key"] == "[REDACTED]"
    assert args["headers"] == {"Authorization": "[REDACTED]", "X-Api-Key": "[REDACTED]"}
    assert args["access_token"] == "[REDACTED]"
    assert args["max_tokens"] == 50


def test_custom_redact_and_unqualified_names(tracer):
    session = instrument_mcp_session(
        FakeSession(), tracer, server_name="crm", qualify_names=False, redact_keys=(),
        redact=lambda v: {k: "***" for k in v} if isinstance(v, dict) else "***",
    )

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("lookup_customer", {"email": "a@b.com"})

    _run(agent())
    tc = tracer.last_trace().tool_calls()[0]
    assert tc.name == "lookup_customer"
    assert tc.args == {"email": "***"}
    assert tc.result == "***"


def test_list_tools_optional(tracer):
    session = instrument_mcp_session(FakeSession(), tracer, server_name="s", trace_list_tools=True)

    async def agent():
        async with trace_run(tracer):
            await session.list_tools()

    _run(agent())
    tc = tracer.last_trace().tool_calls()[0]
    assert tc.name == "s/list_tools"
    assert tc.result == {"tools": ["search", "fetch"]}


def test_uninstrument_and_reinstrument(tracer):
    raw = FakeSession()
    session = instrument_mcp_session(raw, tracer, server_name="a")
    instrument_mcp_session(session, tracer, server_name="b")
    seen = []
    instrument_mcp_session(session, tracer, server_name="c", on_tool_call=seen.append)
    _run(session.call_tool("x", {}))
    assert [tc.name for tc in seen] == ["c/x"]
    uninstrument_mcp_session(session)
    assert "call_tool" not in vars(session)
    _run(session.call_tool("y", {}))
    assert len(seen) == 1
    uninstrument_mcp_session(session)


def test_nested_instrumentation_records_once(tracer):
    inner = instrument_mcp_session(FakeSession(), tracer, server_name="s")

    class Outer:
        async def call_tool(self, name, arguments=None):
            return await inner.call_tool(name, arguments)

    seen = []
    outer = instrument_mcp_session(Outer(), tracer, server_name="s", on_tool_call=seen.append)
    _run(outer.call_tool("search", {}))
    assert [tc.name for tc in seen] == ["s/search"]


def test_server_name_detected_from_session(tracer):
    session = FakeSession()
    session.server_info = SimpleNamespace(name="filesystem")
    instrument_mcp_session(session, tracer)
    seen = []
    instrument_mcp_session(session, tracer, on_tool_call=seen.append)
    _run(session.call_tool("read_file", {"path": "/tmp/x"}))
    assert seen[0].name == "filesystem/read_file"


def test_unsampled_success_dropped_failure_kept():
    tracer = CortexTracer(project="p", sample_rate=0.0)
    session = instrument_mcp_session(FakeSession(), tracer, server_name="s")

    async def ok():
        async with trace_run(tracer):
            await session.call_tool("search", {})

    async def bad():
        async with trace_run(tracer):
            await session.call_tool("explode", {})

    _run(ok())
    assert tracer.traces() == []
    with pytest.raises(ConnectionError):
        _run(bad())
    trace = tracer.last_trace()
    assert trace.metadata["captured_reason"] == "error"
    assert trace.metadata["sampled"] is False
    assert trace.tool_calls()[0].name == "s/explode"


def test_hosted_flush_runs_off_event_loop(monkeypatch):
    tracer = CortexTracer(project="p", api_key="cxo-test", sample_rate=1.0)
    flushed = []
    monkeypatch.setattr(tracer, "_flush_trace", lambda t: flushed.append(t))
    session = instrument_mcp_session(FakeSession(), tracer)

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("search", {})

    _run(agent())
    assert flushed == [tracer.last_trace()]


def test_tool_accuracy_matches_bare_and_qualified_names(tracer):
    from cortexops.metrics import ToolAccuracyMetric
    from cortexops.models import EvalCase

    session = instrument_mcp_session(FakeSession(), tracer, server_name="github")

    async def agent():
        async with trace_run(tracer):
            await session.call_tool("get_issue", {})

    _run(agent())
    trace = tracer.last_trace()
    metric = ToolAccuracyMetric()
    for expected in (["get_issue"], ["github/get_issue"]):
        assert metric.score(EvalCase(id="c", input="x", expected_tool_calls=expected), trace)[0] == 100.0
    score, kind, _ = metric.score(EvalCase(id="c", input="x", expected_tool_calls=["jira/get_issue"]), trace)
    assert score == 0.0 and kind == FailureKind.TOOL_CALL_MISMATCH


def test_truncate_value_containers_and_models():
    data = {"items": list(range(60)), "nested": {"deep": "y" * 30}}
    out = truncate_value(data, max_chars=10)
    assert len(out["items"]) == 51 and out["items"][-1] == "...[10 more items]"
    assert out["nested"]["deep"].endswith("[truncated 20 chars]")
    trace_dump = truncate_value(CortexTracer(project="p")._new_trace({}, sampled=True), max_chars=50)
    assert trace_dump["project"] == "p"
    assert truncate_value(object(), max_chars=5).endswith("chars]")
