"""Tracer is usable across sequential calls (thread-local MVP)."""

import asyncio
import contextvars
import threading

from cortexops import CortexTracer


def test_sequential_traces_isolated():
    tracer = CortexTracer(project="p", sample_rate=1.0)

    def agent(inp: dict) -> dict:
        return {"output": inp["input"]}

    wrapped = tracer.wrap(agent)
    wrapped({"input": "one"})
    wrapped({"input": "two"})
    traces = tracer.traces()
    assert len(traces) == 2
    assert traces[0].trace_id != traces[1].trace_id


def test_use_prompt_isolated_across_asyncio_tasks():
    """Concurrent tasks must not see each other's use_prompt label (issue #49)."""
    tracer = CortexTracer(project="p", sample_rate=1.0)

    async def handle(version):
        with tracer.use_prompt("support", version):
            await asyncio.sleep(0.01)
            return tracer.prompt

    async def main():
        return await asyncio.gather(handle(1), handle(2))

    assert asyncio.run(main()) == [("support", "1"), ("support", "2")]
    assert tracer.prompt is None


def test_use_prompt_inherited_by_child_tasks():
    """Tasks created inside the block inherit the label (context copy at creation)."""
    tracer = CortexTracer(project="p", sample_rate=1.0)

    async def child():
        return tracer.prompt

    async def main():
        with tracer.use_prompt("support", "v3"):
            return await asyncio.gather(child(), child())

    assert asyncio.run(main()) == [("support", "v3"), ("support", "v3")]


def test_use_prompt_propagates_to_to_thread():
    """asyncio.to_thread copies the context, so the label is visible there."""
    tracer = CortexTracer(project="p", sample_rate=1.0)

    async def main():
        with tracer.use_prompt("support", "v7"):
            return await asyncio.to_thread(lambda: tracer.prompt)

    assert asyncio.run(main()) == ("support", "v7")


def test_use_prompt_propagates_through_run_in_executor():
    """Tracer-scheduled executor work keeps the label via copy_context (issue #49)."""
    from unittest.mock import MagicMock

    from tests.helpers import make_framework_mock

    tracer = CortexTracer(project="p", sample_rate=1.0)
    mock = make_framework_mock("CompiledStateGraph", "langgraph.graph.graph")
    mock.invoke = MagicMock(return_value={"ok": True})
    wrapped = tracer.wrap(mock)

    async def main():
        with tracer.use_prompt("support", "v8"):
            return await wrapped.ainvoke({"messages": []})

    assert asyncio.run(main()) == {"ok": True}
    trace = tracer.last_trace()
    assert trace.prompt_name == "support"
    assert trace.prompt_version == "v8"


def test_use_prompt_isolated_across_threads():
    """Plain threads get their own context; labels do not leak between them."""
    tracer = CortexTracer(project="p", sample_rate=1.0)
    seen = {}
    barrier = threading.Barrier(2)

    def work(version):
        with tracer.use_prompt("support", version):
            barrier.wait(timeout=10)
            seen[version] = tracer.prompt

    threads = [threading.Thread(target=work, args=(v,)) for v in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"a": ("support", "a"), "b": ("support", "b")}
    assert tracer.prompt is None


def test_use_prompt_propagates_via_copy_context():
    """Explicit copy_context propagation carries the label into a worker thread."""
    tracer = CortexTracer(project="p", sample_rate=1.0)
    seen = []

    def work():
        seen.append(tracer.prompt)

    with tracer.use_prompt("support", "v9"):
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(work))
        t.start()
        t.join()
    assert seen == [("support", "v9")]


def test_use_prompt_nesting_restores():
    tracer = CortexTracer(project="p", sample_rate=1.0)
    with tracer.use_prompt("outer", "v1"):
        assert tracer.prompt == ("outer", "v1")
        with tracer.use_prompt("inner", "v2"):
            assert tracer.prompt == ("inner", "v2")
        assert tracer.prompt == ("outer", "v1")
    assert tracer.prompt is None


def test_set_prompt_default_and_clear():
    """set_prompt stays a tracer-wide default; use_prompt overrides it locally."""
    tracer = CortexTracer(project="p", sample_rate=1.0)
    assert tracer.prompt is None
    tracer.set_prompt("refund-system", "v3")
    assert tracer.prompt == ("refund-system", "v3")
    with tracer.use_prompt("support", "v1"):
        assert tracer.prompt == ("support", "v1")
    assert tracer.prompt == ("refund-system", "v3")
    tracer.clear_prompt()
    assert tracer.prompt is None


def test_trace_carries_context_local_prompt():
    tracer = CortexTracer(project="p", sample_rate=1.0)

    def agent(inp: dict) -> dict:
        return {"ok": True}

    wrapped = tracer.wrap(agent)
    with tracer.use_prompt("support", "v5"):
        wrapped({"input": "x"})
    trace = tracer.last_trace()
    assert trace.prompt_name == "support"
    assert trace.prompt_version == "v5"
