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
