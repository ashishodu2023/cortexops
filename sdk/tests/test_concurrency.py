"""Tracer is usable across sequential calls (thread-local MVP)."""

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
