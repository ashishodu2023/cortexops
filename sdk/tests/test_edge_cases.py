"""Edge cases."""

from cortexops import CortexTracer, RunStatus


def test_empty_input(tracer):
    def agent(inp: dict) -> dict:
        return {"output": "ok"}

    wrapped = tracer.wrap(agent)
    wrapped({})
    assert tracer.last_trace().status == RunStatus.COMPLETED


def test_non_dict_output(tracer):
    def agent(inp: dict):
        return "plain-string"

    wrapped = tracer.wrap(agent)
    assert wrapped({"input": "x"}) == "plain-string"
    assert tracer.last_trace() is not None
