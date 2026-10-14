import asyncio
from unittest.mock import AsyncMock, MagicMock

from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_pydantic_ai_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("Agent", "pydantic_ai.agent")
    result = MagicMock()
    result.data = "refund_approved"
    mock.run_sync = MagicMock(return_value=result)
    wrapped = tracer.wrap(mock)
    assert wrapped.run_sync("Process refund").data == "refund_approved"
    assert tracer.last_trace().status == RunStatus.COMPLETED


def _stub_agent():
    mock = make_framework_mock("Agent", "pydantic_ai.agent")
    result = MagicMock()
    result.data = "refund_approved"
    mock.run_sync = MagicMock(return_value=result)
    mock.run = AsyncMock(return_value=result)
    return mock, result


def test_pydantic_ai_async_run_traced():
    """Async run() must go through the traced path (issue #49)."""
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock, _ = _stub_agent()
    wrapped = tracer.wrap(mock)
    out = asyncio.run(wrapped.run("Process refund"))
    assert out.data == "refund_approved"
    trace = tracer.last_trace()
    assert trace is not None
    assert trace.status == RunStatus.COMPLETED


def test_pydantic_ai_async_run_error_traced():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock, _ = _stub_agent()
    mock.run = AsyncMock(side_effect=RuntimeError("boom"))
    wrapped = tracer.wrap(mock)
    try:
        asyncio.run(wrapped.run("x"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
    trace = tracer.last_trace()
    assert trace.status == RunStatus.FAILED
    assert "boom" in trace.failure_detail


class _StubStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_pydantic_ai_run_stream_traced():
    """run_stream() opens a trace that closes when the stream completes (issue #49)."""
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock, _ = _stub_agent()
    mock.run_stream = MagicMock(return_value=_StubStream())
    wrapped = tracer.wrap(mock)

    async def consume():
        async with wrapped.run_stream("hi") as stream:
            async for _ in stream:
                pass

    asyncio.run(consume())
    trace = tracer.last_trace()
    assert trace is not None
    assert trace.status == RunStatus.COMPLETED


def test_pydantic_ai_run_stream_error_traced():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock, _ = _stub_agent()

    class _FailStream(_StubStream):
        async def __aexit__(self, *exc):
            raise RuntimeError("stream blew up")

    mock.run_stream = MagicMock(return_value=_FailStream())
    wrapped = tracer.wrap(mock)

    async def consume():
        async with wrapped.run_stream("hi"):
            pass

    try:
        asyncio.run(consume())
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
    trace = tracer.last_trace()
    assert trace.status == RunStatus.FAILED


def test_concurrent_async_runs_isolate_current_trace():
    """Overlapping async runs must not land each other's nodes (review #70)."""
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock, result = _stub_agent()

    async def fake_run(prompt, **kwargs):
        await asyncio.sleep(0.05 if prompt == "A" else 0.02)
        with tracer.trace_node(f"node-{prompt}"):
            pass
        return result

    mock.run = fake_run
    wrapped = tracer.wrap(mock)

    async def both():
        await asyncio.gather(wrapped.run("A"), wrapped.run("B"))

    asyncio.run(both())
    by_prompt = {t.input["prompt"]: t for t in tracer.traces()}
    assert [n.node_name for n in by_prompt["A"].nodes] == ["node-A"]
    assert [n.node_name for n in by_prompt["B"].nodes] == ["node-B"]
    assert tracer._current_trace is None


def test_pydantic_ai_run_stream_startup_failure_traced():
    """A stream whose __aenter__ raises still gets a FAILED trace (review #70)."""
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock, _ = _stub_agent()

    class _FailEnterStream:
        async def __aenter__(self):
            raise RuntimeError("connect failed")

        async def __aexit__(self, *exc):
            return False

    mock.run_stream = MagicMock(return_value=_FailEnterStream())
    wrapped = tracer.wrap(mock)

    async def consume():
        async with wrapped.run_stream("hi"):
            pass

    try:
        asyncio.run(consume())
    except RuntimeError as exc:
        assert "connect failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    trace = tracer.last_trace()
    assert trace is not None
    assert trace.status == RunStatus.FAILED
    assert "connect failed" in trace.failure_detail
    assert tracer._current_trace is None


def test_pydantic_ai_user_prompt_kwarg_forwarded():
    """wrapped.run/run_sync/run_stream accept PydanticAI's user_prompt kwarg."""
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock, result = _stub_agent()
    wrapped = tracer.wrap(mock)

    assert wrapped.run_sync(user_prompt="Process refund").data == "refund_approved"
    mock.run_sync.assert_called_once_with("Process refund")

    out = asyncio.run(wrapped.run(user_prompt="hi"))
    assert out.data == "refund_approved"
    mock.run.assert_called_once_with("hi")

    mock.run_stream = MagicMock(return_value=_StubStream())

    async def consume():
        async with wrapped.run_stream(user_prompt="hi") as stream:
            async for _ in stream:
                pass

    asyncio.run(consume())
    mock.run_stream.assert_called_once_with("hi")
