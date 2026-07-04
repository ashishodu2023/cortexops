from unittest.mock import MagicMock
from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_smolagents_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("CodeAgent", "smolagents.agents")
    mock.run = MagicMock(return_value="done")
    wrapped = tracer.wrap(mock)
    assert wrapped.run("task") == "done"
    assert tracer.last_trace().status == RunStatus.COMPLETED
